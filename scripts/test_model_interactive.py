#!/usr/bin/env python3
"""
Interactive Model Test - Manual testing of LLM + tools

Loads the actual model and tool system so you can:
- Give it instructions manually
- Watch it execute tools in real-time
- See the full execution flow
- Diagnose issues by testing specific scenarios

Usage:
    python scripts/test_model_interactive.py
    
Then type your instructions and press Enter.
Type 'quit' to exit.
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.services.unified_llm import get_llm_service
from core.tools.tool_registry import get_tool_registry


class InteractiveModelTest:
    """Interactive test harness for model + tools"""
    
    def __init__(self):
        self.llm = None
        self.tool_registry = None
        self.conversation_history = []
        
    async def initialize(self):
        """Initialize all systems"""
        print("=" * 80)
        print("TORIN INTERACTIVE MODEL TEST")
        print("=" * 80)
        print(f"Started: {datetime.now().isoformat()}")
        print()
        
        print("Initializing systems...")
        print()
        
        # Initialize LLM
        print("1. Loading LLM model...")
        print("   This will take 30-60 seconds to load 18GB model into memory...")
        self.llm = get_llm_service()
        
        # Force model initialization
        if hasattr(self.llm, '_ensure_model_loaded'):
            await self.llm._ensure_model_loaded()
        elif hasattr(self.llm, 'initialize'):
            await self.llm.initialize()
        
        # Verify model is actually loaded
        if self.llm.model_loaded:
            print("   ✓ Model loaded and ready")
        else:
            print("   ✗ Model failed to load!")
            raise RuntimeError("Model not loaded")
        print()
        
        # Initialize tool registry
        print("2. Loading tools...")
        self.tool_registry = get_tool_registry()
        all_tools = list(self.tool_registry.tools.values())
        print(f"   ✓ {len(all_tools)} tools loaded")
        print()
        
        print("=" * 80)
        print("READY FOR TESTING")
        print("=" * 80)
        print()
        print("Available tools:")
        all_tools = list(self.tool_registry.tools.values())
        tool_names = [tool.name for tool in all_tools[:10]]
        for name in tool_names:
            print(f"  - {name}")
        if len(all_tools) > 10:
            print(f"  ... and {len(all_tools) - 10} more")
        print()
        print("=" * 80)
        print()
        print("Type your instruction and press Enter.")
        print("The model will execute tools as needed.")
        print("Type 'quit' to exit, 'clear' to reset conversation.")
        print()
    
    async def run_interactive_loop(self):
        """Main interactive loop"""
        while True:
            try:
                # Get user input
                print("\n" + "─" * 80)
                user_input = input("YOU: ").strip()
                print()
                
                if not user_input:
                    continue
                
                if user_input.lower() == 'quit':
                    print("Exiting...")
                    break
                
                if user_input.lower() == 'clear':
                    self.conversation_history = []
                    print("✓ Conversation cleared")
                    continue
                
                # Process the instruction
                await self.process_instruction(user_input)
                
            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"\n✗ Error: {e}")
                import traceback
                traceback.print_exc()
    
    async def process_instruction(self, instruction: str):
        """Process a single instruction"""
        print(f"{'─' * 80}")
        print("PROCESSING...")
        print(f"{'─' * 80}")
        print()
        
        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": instruction
        })
        
        # Prepare messages
        system_prompt = """You are Torin, an AI assistant. You have access to tools.
When given an instruction:
1. Think about what needs to be done
2. Use available tools to accomplish the task
3. Provide clear feedback about what you're doing

Be direct and use tools actively."""
        
        messages = [
            {"role": "system", "content": system_prompt}
        ] + self.conversation_history
        
        # Get available tools
        tools = [tool.to_openai_schema() for tool in self.tool_registry.tools.values()]
        
        # Call LLM
        print("Calling LLM...")
        start_time = datetime.now()
        
        response = await self.llm.generate_with_messages(
            messages=messages,
            tools=tools,
            temperature=0.7,
            max_tokens=2000
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"✓ LLM response received ({elapsed:.2f}s)")
        print()
        
        # Process response
        await self.handle_response(response)
    
    async def handle_response(self, response: dict):
        """Handle LLM response and execute tools"""
        # Get text response
        content = response.get('content', '')
        tool_calls = response.get('tool_calls', [])
        
        # Show response
        if content:
            print("TORIN:")
            print(content)
            print()
            
            # Add to history
            self.conversation_history.append({
                "role": "assistant",
                "content": content
            })
        
        # Execute tool calls
        if tool_calls:
            print(f"{'─' * 80}")
            print(f"EXECUTING {len(tool_calls)} TOOL CALLS")
            print(f"{'─' * 80}")
            print()
            
            tool_results = []
            
            for i, tool_call in enumerate(tool_calls, 1):
                func = tool_call.get('function', {})
                tool_name = func.get('name')
                tool_args_str = func.get('arguments', '{}')
                
                # Parse arguments if string
                if isinstance(tool_args_str, str):
                    tool_args = json.loads(tool_args_str)
                else:
                    tool_args = tool_args_str
                
                print(f"Tool {i}/{len(tool_calls)}: {tool_name}")
                print(f"Arguments: {json.dumps(tool_args, indent=2)}")
                print()
                
                # Execute tool
                try:
                    print(f"Executing...")
                    start_time = datetime.now()
                    
                    result = await self.tool_registry.execute_tool(
                        tool_name=tool_name,
                        parameters=tool_args
                    )
                    
                    elapsed = (datetime.now() - start_time).total_seconds()
                    
                    print(f"✓ Completed ({elapsed:.2f}s)")
                    result_str = result.output if result.success else result.error
                    print(f"Result: {str(result_str)[:500]}")
                    if len(str(result_str)) > 500:
                        print(f"... (truncated, {len(str(result_str))} total chars)")
                    print()
                    
                    tool_results.append({
                        "tool": tool_name,
                        "result": str(result_str)
                    })
                    
                except Exception as e:
                    print(f"✗ Error: {e}")
                    print()
                    tool_results.append({
                        "tool": tool_name,
                        "error": str(e)
                    })
            
            # Get follow-up response
            if tool_results:
                print(f"{'─' * 80}")
                print("GETTING FOLLOW-UP RESPONSE...")
                print(f"{'─' * 80}")
                print()
                
                # Add tool results to history
                tool_summary = "\n".join([
                    f"{r['tool']}: {r.get('result', r.get('error'))[:200]}"
                    for r in tool_results
                ])
                self.conversation_history.append({
                    "role": "user",
                    "content": f"Tool results:\n{tool_summary}"
                })
                
                messages = [
                    {"role": "system", "content": "You are Torin. Process the tool results and provide feedback."}
                ] + self.conversation_history
                tools = [tool.to_openai_schema() for tool in self.tool_registry.tools.values()]
                
                start_time = datetime.now()
                follow_up = await self.llm.generate_with_messages(
                    messages=messages,
                    tools=tools,
                    temperature=0.7,
                    max_tokens=1000
                )
                elapsed = (datetime.now() - start_time).total_seconds()
                print(f"✓ Follow-up received ({elapsed:.2f}s)")
                print()
                
                # Process follow-up (recursive)
                await self.handle_response(follow_up)
        else:
            print("No tool calls requested.")


async def main():
    test = InteractiveModelTest()
    
    try:
        await test.initialize()
        await test.run_interactive_loop()
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
