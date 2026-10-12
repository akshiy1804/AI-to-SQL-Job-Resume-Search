
import os
from dotenv import load_dotenv

load_dotenv()

required = [
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "GROQ_API_KEY",
]

missing = [key for key in required if not os.getenv(key)]

if missing:
    print("Missing settings:", ", ".join(missing))
else:
    print("All environment settings loaded successfully!")
    print("Database:", os.getenv("DB_NAME"))
    print("Groq API key: Present (hidden)")
