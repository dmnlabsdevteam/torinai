#!/usr/bin/env python3
"""
Drift Event Publisher - Publishes normalized drift events to NATS event bus
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
import logging

import nats
from nats.errors import ConnectionClosedError, TimeoutError

logger = logging.getLogger(__name__)

@dataclass
class DriftEvent:
    """Normalized drift detection event"""
    event_id: str
    model_id: str
    dataset_id: str
    timestamp: float
    summary: Dict[str, Any]
    confidence_score: float
    severity: str  # "low", "medium", "high", "critical"
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_monitor_result(
        cls,
        model_id: str,
        dataset_id: str,
        monitor_summary: Dict[str, Any],
        evaluation_result: Dict[str, Any]
    ) -> "DriftEvent":
        """Create DriftEvent from monitor results"""
        
        # Calculate confidence score based on statistical significance
        max_psi = evaluation_result.get("max_psi", 0.0)
        share_drifted = evaluation_result.get("share_drifted", 0.0)
        
        # Normalize confidence score (0.0 - 1.0)
        psi_confidence = min(max_psi / 1.0, 1.0)  # PSI > 1.0 is very high drift
        share_confidence = share_drifted
        confidence_score = max(psi_confidence, share_confidence)
        
        # Determine severity
        severity = cls._calculate_severity(evaluation_result)
        
        return cls(
            event_id=str(uuid.uuid4()),
            model_id=model_id,
            dataset_id=dataset_id,
            timestamp=time.time(),
            summary=monitor_summary,
            confidence_score=confidence_score,
            severity=severity,
            metadata={
                "evaluation_status": evaluation_result.get("status"),
                "reasons": evaluation_result.get("reasons", []),
                "feature_count": len(monitor_summary.get("features", {})),
                "publisher": "evidently_monitor"
            }
        )
    
    @staticmethod
    def _calculate_severity(evaluation_result: Dict[str, Any]) -> str:
        """Calculate severity based on evaluation metrics"""
        status = evaluation_result.get("status", "ok")
        max_psi = evaluation_result.get("max_psi", 0.0)
        share_drifted = evaluation_result.get("share_drifted", 0.0)
        
        if status == "fail" or max_psi > 0.5 or share_drifted > 0.8:
            return "critical"
        elif status == "warn" or max_psi > 0.25 or share_drifted > 0.5:
            return "high"
        elif max_psi > 0.1 or share_drifted > 0.2:
            return "medium"
        else:
            return "low"


class DriftEventPublisher:
    """Publishes drift events to NATS event bus"""
    
    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[nats.js.JetStreamContext] = None
        self.connected = False
        
    async def connect(self) -> None:
        """Connect to NATS server"""
        try:
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            
            # Ensure drift events stream exists
            try:
                await self.js.stream_info("DRIFT_EVENTS")
            except Exception:
                # Create stream if it doesn't exist
                await self.js.add_stream(
                    name="DRIFT_EVENTS",
                    subjects=["drift.events.*"],
                    retention=nats.js.RetentionPolicy.WORK_QUEUE,
                    max_age=86400 * 7,  # 7 days retention
                    storage=nats.js.StorageType.FILE
                )
                logger.info("Created DRIFT_EVENTS stream")
            
            self.connected = True
            logger.info(f"Connected to NATS at {self.nats_url}")
            
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from NATS server"""
        if self.nc and not self.nc.is_closed:
            await self.nc.close()
            self.connected = False
            logger.info("Disconnected from NATS")
    
    async def publish_drift_event(self, event: DriftEvent) -> bool:
        """Publish a drift event to the event bus"""
        if not self.connected or not self.js:
            raise ConnectionError("Not connected to NATS")
        
        try:
            # Subject follows pattern: drift.events.{severity}.{model_id}
            subject = f"drift.events.{event.severity}.{event.model_id}"
            
            # Serialize event
            event_data = json.dumps(event.to_dict()).encode()
            
            # Publish with metadata
            headers = {
                'event-id': event.event_id,
                'model-id': event.model_id,
                'dataset-id': event.dataset_id,
                'severity': event.severity,
                'confidence': str(event.confidence_score),
                'timestamp': str(event.timestamp)
            }
            
            ack = await self.js.publish(
                subject,
                event_data,
                headers=headers,
                timeout=10.0
            )
            
            logger.info(
                f"Published drift event {event.event_id} for model {event.model_id} "
                f"(severity: {event.severity}, confidence: {event.confidence_score:.3f})"
            )
            
            return True
            
        except (ConnectionClosedError, TimeoutError) as e:
            logger.error(f"Failed to publish event {event.event_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error publishing event {event.event_id}: {e}")
            return False
    
    async def publish_from_monitor_result(
        self,
        model_id: str,
        dataset_id: str,
        monitor_summary: Dict[str, Any],
        evaluation_result: Dict[str, Any]
    ) -> Optional[DriftEvent]:
        """Create and publish drift event from monitor results"""
        
        # Only publish if drift is detected
        if evaluation_result.get("status") == "ok":
            logger.debug(f"No drift detected for model {model_id}, skipping event publication")
            return None
        
        # Create drift event
        event = DriftEvent.from_monitor_result(
            model_id=model_id,
            dataset_id=dataset_id,
            monitor_summary=monitor_summary,
            evaluation_result=evaluation_result
        )
        
        # Publish event
        success = await self.publish_drift_event(event)
        
        if success:
            return event
        else:
            logger.error(f"Failed to publish drift event for model {model_id}")
            return None


class EventPublisherService:
    """Service wrapper for the drift event publisher with lifecycle management"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.publisher = DriftEventPublisher(
            nats_url=config.get("nats_url", "nats://localhost:4222")
        )
        self.running = False
    
    async def start(self) -> None:
        """Start the publisher service"""
        try:
            await self.publisher.connect()
            self.running = True
            logger.info("Drift event publisher service started")
        except Exception as e:
            logger.error(f"Failed to start publisher service: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the publisher service"""
        if self.running:
            await self.publisher.disconnect()
            self.running = False
            logger.info("Drift event publisher service stopped")
    
    async def publish_drift_detection(
        self,
        model_id: str,
        dataset_id: str,
        monitor_summary: Dict[str, Any],
        evaluation_result: Dict[str, Any]
    ) -> Optional[DriftEvent]:
        """Publish drift detection event"""
        if not self.running:
            raise RuntimeError("Publisher service not running")
        
        return await self.publisher.publish_from_monitor_result(
            model_id=model_id,
            dataset_id=dataset_id,
            monitor_summary=monitor_summary,
            evaluation_result=evaluation_result
        )
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


# Integration with existing monitor
async def publish_monitor_results(
    model_id: str,
    dataset_id: str,
    monitor_summary: Dict[str, Any],
    evaluation_result: Dict[str, Any],
    nats_url: str = "nats://localhost:4222"
) -> Optional[DriftEvent]:
    """Convenience function to publish monitor results"""
    
    config = {"nats_url": nats_url}
    
    async with EventPublisherService(config) as publisher:
        return await publisher.publish_drift_detection(
            model_id=model_id,
            dataset_id=dataset_id,
            monitor_summary=monitor_summary,
            evaluation_result=evaluation_result
        )


if __name__ == "__main__":
    # Test the publisher
    import asyncio
    
    async def test_publisher():
        """Test drift event publishing"""
        logging.basicConfig(level=logging.INFO)
        
        # Sample monitor results
        monitor_summary = {
            "dataset_drift": True,
            "share_drifted_features": 0.6,
            "features": {
                "feature1": {"drift_score": 0.45, "drift_detected": True, "stattest": "PSI"},
                "feature2": {"drift_score": 0.12, "drift_detected": False, "stattest": "KS"},
            }
        }
        
        evaluation_result = {
            "status": "warn",
            "max_psi": 0.45,
            "share_drifted": 0.6,
            "reasons": ["max_psi=0.450 share_drifted=0.600"]
        }
        
        # Publish event
        event = await publish_monitor_results(
            model_id="test_model_v1",
            dataset_id="prod_dataset_2025_09",
            monitor_summary=monitor_summary,
            evaluation_result=evaluation_result
        )
        
        if event:
            print(f"Successfully published event: {event.event_id}")
        else:
            print("Failed to publish event")
    
    asyncio.run(test_publisher())