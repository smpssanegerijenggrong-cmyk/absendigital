"""Jalankan: python start.py  | lalu buka http://localhost:8000"""
from dotenv import load_dotenv
load_dotenv()
import uvicorn
if __name__ == '__main__':
    uvicorn.run('app.main:app',host='0.0.0.0',port=8000,workers=1,reload=False)
