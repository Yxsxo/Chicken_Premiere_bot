import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=200,
    messages=[
        {
            "role": "user",
            "content": "Съел 3 яйца и банан. Прикинь примерно калорийность и ответь одной короткой фразой.",
        }
    ],
)

print(response.content[0].text)
