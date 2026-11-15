import os #Python’s built-in module for talking to the operating system. We use one function from it, os.getenv(...), which reads an environment variable
from dotenv import load_dotenv #From the python-dotenv package (installed with pip), take the load_dotenv function. It reads your .env file.
from langchain_google_genai import ChatGoogleGenerativeAI #From LangChain’s Gemini package, take the ChatGoogleGenerativeAI class, a blueprint for creating a Gemini model object.

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