# filepath: d:\GitHub\api-summvid\startup.sh
#!/bin/bash
pip install -r requirements.txt
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app