from openai import OpenAI

client = OpenAI(
    base_url="https://api.forge.tensorblock.co/v1", 
    api_key="forge-NDUw45089a90aca5267f36c5605b421906df",  
)
    
# models = client.models.list()

completion = client.chat.completions.create(
    model="OpenAI/gpt-4o",
    messages=[
        {"role": "developer", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ]
)

print(completion.choices[0].message)