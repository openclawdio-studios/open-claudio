import asyncio
from main import ExtendedReActAgent

async def test():
    agent = ExtendedReActAgent()
    await agent.initialize()
    print("Agent initialized")
    
    prompt = "por favor baja la persiana del salon"
    print(f"Sending prompt: {prompt}")
    
    result = await agent.process_user_input(prompt)
    print(f"Result: {result}")
    await agent.shutdown()

asyncio.run(test())
