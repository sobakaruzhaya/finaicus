from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
from api import local
# from starlette.staticfiles import StaticFiles
# from core.config import settings
from dotenv import load_dotenv


load_dotenv()

app = FastAPI()


app.include_router(local.router, prefix="/api/local", tags=["local"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)