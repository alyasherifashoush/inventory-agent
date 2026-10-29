import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

# 1. Load GOOGLE_API_KEY and GEMINI_MODEL from the .env file
load_dotenv()

# 2. Create the model object (LangChain's wrapper around Gemini)
llm = ChatGoogleGenerativeAI(
    model=os.getenv("GEMINI_MODEL"),
    temperature=0,  # 0 = consistent, factual answers; higher = more creative
)

# 3. Send a message and print the reply
response = llm.invoke("In one sentence, why do supermarkets discount items near their expiry date?")
print(response.content)