import subprocess
import time
import os
import sys
import signal

# Configuration
FLASK_APP = "app.py"
NGINX_CONF = "nginx.conf"
NGINX_EXE = "nginx.exe"

processes = []

def start_flask():
    print("Starting Flask Backend (Port 5000)...")
    
    # Use gunicorn if available (Production/Linux), fallback to flask (Development/Windows)
    try:
        # Check if gunicorn exists in path
        subprocess.run(["gunicorn", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("Using Gunicorn (Production Server)")
        cmd = ["gunicorn", "-c", "gunicorn_config.py", "app:app"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Gunicorn not found or not supported on this OS. Using Flask Development Server.")
        cmd = [sys.executable, FLASK_APP]

    p = subprocess.Popen(cmd, 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.STDOUT, 
                         universal_newlines=True)
    processes.append(p)
    return p

def start_nginx():
    print("Starting Nginx (Port 8080)...")
    # -c requires an absolute path on Windows
    nginx_conf_abs = os.path.abspath(NGINX_CONF)
    p = subprocess.Popen([NGINX_EXE, "-c", nginx_conf_abs], 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.STDOUT)
    processes.append(p)
    return p

def cleanup(sig=None, frame=None):
    print("\nStopping Cloud Storage System...")
    
    # Stop Nginx properly
    try:
        subprocess.run([NGINX_EXE, "-s", "stop"], check=False)
        print("Nginx stopped.")
    except:
        pass
    
    # Kill remaining processes
    for p in processes:
        try:
            p.terminate()
        except:
            pass
    
    print("Cleanup complete. Goodbye!")
    sys.exit(0)

if __name__ == "__main__":
    # Ensure logs and temp folders exist for Nginx
    os.makedirs("logs", exist_ok=True)
    os.makedirs("temp", exist_ok=True)
    os.makedirs("hls", exist_ok=True)

    # Handle Ctrl+C
    signal.signal(signal.SIGINT, cleanup)

    try:
        flask_p = start_flask()
        nginx_p = start_nginx()
        
        print("\n" + "="*40)
        print("SYSTEM STARTED SUCCESSFULLY")
        print("Access the app at: http://localhost:8080")
        print("="*40)
        print("Press Ctrl+C to stop everything.")
        
        # Keep the script running and print Flask logs
        while True:
            line = flask_p.stdout.readline()
            if line:
                print(f"[Flask] {line.strip()}")
            time.sleep(0.1)
            
    except Exception as e:
        print(f"Error starting system: {e}")
        cleanup()
