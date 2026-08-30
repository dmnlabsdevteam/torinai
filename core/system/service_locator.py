"""Service location and dependency resolution.

MOVED OUT OF `core/security/`. It was filed there as
`service_abstractions.py` and contains no security logic whatsoever -- it is a
generic DI container, and its location made it look like part of the security
subsystem while having nothing to do with it.

NO CONSUMERS. Stated plainly rather than left to be discovered: nothing in this
codebase resolves dependencies through this. The pattern actually in use is
module-level singleton getters (`get_rule_store()`, `get_safety_framework()`,
`get_neural_bridge()`), which is simpler and works. This is kept because it is
now correct and may be adopted deliberately; it is not evidence that dependency
injection is in use.

The defects below were all in the parts nothing had ever exercised.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set, Union, Type, TypeVar, Generic, Callable
from dataclasses import dataclass
from enum import Enum

T = TypeVar('T')


class ServiceScope(Enum):
    """Service lifetime scopes"""
    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


@dataclass
class ServiceDescriptor:
    """Service registration descriptor"""
    service_type: Type
    implementation_type: Optional[Type] = None
    factory: Optional[Callable] = None
    instance: Optional[Any] = None
    scope: ServiceScope = ServiceScope.TRANSIENT
    dependencies: Optional[List[Type]] = None


class IServiceLocator(ABC):
    """Interface for service location and dependency resolution"""
    
    @abstractmethod
    def register_singleton(self, service_type: Type[T], implementation: Union[Type[T], T, Callable[[], T]]) -> None:
        """Register a singleton service"""
        pass
    
    @abstractmethod
    def register_scoped(self, service_type: Type[T], implementation: Union[Type[T], Callable[[], T]]) -> None:
        """Register a scoped service"""
        pass
    
    @abstractmethod
    def register_transient(self, service_type: Type[T], implementation: Union[Type[T], Callable[[], T]]) -> None:
        """Register a transient service"""
        pass
    
    @abstractmethod
    def get_service(self, service_type: Type[T]) -> T:
        """Get an instance of the requested service"""
        pass
    
    @abstractmethod
    def get_services(self, service_type: Type[T]) -> List[T]:
        """Get all instances of the requested service type"""
        pass
    
    @abstractmethod
    def is_registered(self, service_type: Type) -> bool:
        """Check if a service type is registered"""
        pass


class ServiceLocator(IServiceLocator):
    """Concrete implementation of service locator"""
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._instances: Dict[Type, Any] = {}
        self._scoped_instances: Dict[str, Dict[Type, Any]] = {}
        self._current_scope: Optional[str] = None
    
    def register_singleton(self, service_type: Type[T], implementation: Union[Type[T], T, Callable[[], T]]) -> None:
        """Register a singleton service"""
        if isinstance(implementation, type):
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                implementation_type=implementation,
                scope=ServiceScope.SINGLETON
            )
        elif callable(implementation):
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                factory=implementation,
                scope=ServiceScope.SINGLETON
            )
        else:
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                instance=implementation,
                scope=ServiceScope.SINGLETON
            )
            self._instances[service_type] = implementation
    
    def register_scoped(self, service_type: Type[T], implementation: Union[Type[T], Callable[[], T]]) -> None:
        """Register a scoped service"""
        if isinstance(implementation, type):
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                implementation_type=implementation,
                scope=ServiceScope.SCOPED
            )
        else:
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                factory=implementation,
                scope=ServiceScope.SCOPED
            )
    
    def register_transient(self, service_type: Type[T], implementation: Union[Type[T], Callable[[], T]]) -> None:
        """Register a transient service"""
        if isinstance(implementation, type):
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                implementation_type=implementation,
                scope=ServiceScope.TRANSIENT
            )
        else:
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                factory=implementation,
                scope=ServiceScope.TRANSIENT
            )
    
    def get_service(self, service_type: Type[T]) -> T:
        """Get an instance of the requested service"""
        if service_type not in self._services:
            raise ValueError(f"Service {service_type.__name__} is not registered")
        
        descriptor = self._services[service_type]
        
        if descriptor.scope == ServiceScope.SINGLETON:
            if service_type not in self._instances:
                self._instances[service_type] = self._create_instance(descriptor)
            return self._instances[service_type]
        
        elif descriptor.scope == ServiceScope.SCOPED:
            if self._current_scope is None:
                raise RuntimeError("No active scope for scoped service")
            
            if self._current_scope not in self._scoped_instances:
                self._scoped_instances[self._current_scope] = {}
            
            scope_instances = self._scoped_instances[self._current_scope]
            if service_type not in scope_instances:
                scope_instances[service_type] = self._create_instance(descriptor)
            return scope_instances[service_type]
        
        else:  # TRANSIENT
            return self._create_instance(descriptor)
    
    def get_services(self, service_type: Type[T]) -> List[T]:
        """Get all instances of the requested service type"""
        # For now, just return single instance as list
        # Could be extended to support multiple implementations
        return [self.get_service(service_type)]
    
    def is_registered(self, service_type: Type) -> bool:
        """Check if a service type is registered"""
        return service_type in self._services
    
    def begin_scope(self, scope_id: str) -> None:
        """Begin a new service scope"""
        self._current_scope = scope_id
        if scope_id not in self._scoped_instances:
            self._scoped_instances[scope_id] = {}
    
    def end_scope(self, scope_id: str) -> None:
        """End a service scope"""
        if scope_id in self._scoped_instances:
            del self._scoped_instances[scope_id]
        if self._current_scope == scope_id:
            self._current_scope = None
    
    def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """Create an instance from service descriptor"""
        if descriptor.instance is not None:
            return descriptor.instance
        
        if descriptor.factory is not None:
            return descriptor.factory()
        
        if descriptor.implementation_type is not None:
            # `ServiceDescriptor.dependencies` used to be DECLARED AND NEVER
            # READ: a caller could register a service with dependencies and
            # they were silently discarded. Constructor arguments are resolved
            # from the locator here, and a declared dependency that is not
            # registered raises rather than being skipped.
            if descriptor.dependencies:
                resolved = []
                for dependency in descriptor.dependencies:
                    if not self.is_registered(dependency):
                        raise ValueError(
                            f"service {descriptor.service_type} declares a dependency on "
                            f"{dependency}, which is not registered")
                    resolved.append(self.get_service(dependency))
                return descriptor.implementation_type(*resolved)
            return descriptor.implementation_type()
        
        raise ValueError("No way to create instance for service")


class IDependencyInjector(ABC):
    """Interface for dependency injection"""
    
    @abstractmethod
    async def inject_dependencies(self, instance: Any) -> None:
        """Inject dependencies into an instance"""
        pass
    
    @abstractmethod
    def resolve_dependencies(self, target_type: Type) -> List[Any]:
        """Resolve dependencies for a type"""
        pass


class DependencyInjector(IDependencyInjector):
    """Concrete dependency injector implementation"""
    
    def __init__(self, service_locator: IServiceLocator):
        self.service_locator = service_locator
    
    async def inject_dependencies(self, instance: Any) -> None:
        """Async-compatible wrapper. Resolution itself does no I/O."""
        self.inject_dependencies_sync(instance)

    def inject_dependencies_sync(self, instance: Any) -> None:
        """Inject dependencies into an instance using property injection.

        Synchronous because nothing here awaits: resolution reads annotations
        and asks the locator. Offering only an async form is what forced the
        decorator into `create_task` and produced a race.
        """
        # Look for attributes that are interface types
        for attr_name in dir(instance):
            if attr_name.startswith('_') or callable(getattr(instance, attr_name)):
                continue
            
            attr = getattr(instance, attr_name)
            if attr is None:
                # Check if there's a type hint for this attribute
                if hasattr(instance.__class__, '__annotations__'):
                    annotations = instance.__class__.__annotations__
                    if attr_name in annotations:
                        service_type = annotations[attr_name]
                        if self.service_locator.is_registered(service_type):
                            setattr(instance, attr_name, self.service_locator.get_service(service_type))
    
    def resolve_dependencies(self, target_type: Type) -> List[Any]:
        """Resolve constructor dependencies for a type"""
        # Simplified implementation - could use type hints or annotations
        dependencies = []
        
        if hasattr(target_type, '__init__'):
            import inspect
            signature = inspect.signature(target_type.__init__)
            for param_name, param in signature.parameters.items():
                if param_name == 'self':
                    continue
                
                if param.annotation != inspect.Parameter.empty:
                    if self.service_locator.is_registered(param.annotation):
                        dependencies.append(self.service_locator.get_service(param.annotation))
        
        return dependencies


# Global service locator instance
_service_locator: Optional[ServiceLocator] = None


def get_service_locator() -> ServiceLocator:
    """Get the global service locator instance"""
    global _service_locator
    if _service_locator is None:
        _service_locator = ServiceLocator()
    return _service_locator


def configure_services(configuration_func: Callable[[ServiceLocator], None]) -> None:
    """Configure services using a configuration function"""
    locator = get_service_locator()
    configuration_func(locator)


# Decorator for dependency injection
def inject_dependencies(cls):
    """Class decorator that injects declared dependencies at construction.

    THE PREVIOUS VERSION WAS A RACE AND A CRASH. It ended `__init__` with

        asyncio.create_task(injector.inject_dependencies(self))

    which (1) raises `RuntimeError: no running event loop` for any class built
    outside a loop, (2) returns from `__init__` BEFORE injection has run, so the
    object is handed to the caller with its dependencies still None while the
    decorator's name promises they are set, and (3) never awaits the task, so a
    failure inside injection disappears.

    Injection is now synchronous and complete before `__init__` returns. A
    constructor cannot await, and pretending otherwise is what produced the
    race.
    """
    original_init = cls.__init__

    def new_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        DependencyInjector(get_service_locator()).inject_dependencies_sync(self)

    cls.__init__ = new_init
    return cls
    return cls