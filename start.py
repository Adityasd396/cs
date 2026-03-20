import subprocess
import time
import os
import sys
import signal

# Configuration
FLASK_APP = "app.py"
NGINX_CONF = "nginx.conf"
NGINX_PROD_CONF = "nginx_runtime.conf"

# Detect OS and Nginx binary
IS_WINDOWS = sys.platform == "win32"
# On Linux, try 'nginx' command. On Windows, try 'nginx.exe' or 'nginx'
NGINX_CMD = "nginx.exe" if IS_WINDOWS else "nginx"

# Double check if Nginx binary is actually available
def find_nginx():
    import shutil
    binary = shutil.which(NGINX_CMD)
    if not binary and IS_WINDOWS:
        # Check current folder on Windows as fallback
        if os.path.exists("nginx.exe"):
            return os.path.abspath("nginx.exe")
    return binary or NGINX_CMD

NGINX_EXECUTABLE = find_nginx()

processes = []

def prepare_nginx_conf():
    """Ensure nginx.conf is ready for use in the current environment"""
    # Create required local folders if they don't exist
    os.makedirs("logs", exist_ok=True)
    os.makedirs("temp", exist_ok=True)
    os.makedirs("hls", exist_ok=True)
    
    # Check for mime.types file which Nginx needs
    if not os.path.exists("mime.types"):
        # Create a basic mime.types if missing
        with open("mime.types", "w") as f:
            f.write("types {\n    text/html html htm shtml;\n    text/css css;\n    text/xml xml;\n    image/gif gif;\n    image/jpeg jpeg jpg;\n    application/javascript js;\n    application/atom+xml atom;\n    application/rss+xml rss;\n    application/vnd.apple.mpegurl m3u8;\n    video/mp2t ts;\n    video/mp4 mp4;\n    video/mpeg mpeg mpg;\n    video/quicktime mov;\n    video/x-flv flv;\n    video/x-m4v m4v;\n    video/x-mng mng;\n    video/x-ms-asf asx asf;\n    video/x-ms-wmv wmv;\n    video/x-msvideo avi;\n}\n")

    with open(NGINX_CONF, "r") as f:
        content = f.read()
    
    # For now, we'll just copy it to the production conf file
    # This keeps original clean while allowing future dynamic updates
    with open(NGINX_PROD_CONF, "w") as f:
        f.write(content)
    
    return os.path.abspath(NGINX_PROD_CONF)

def start_flask():
    print("Starting Flask Backend (Port 5000)...")
    
    # Use gunicorn if available (Production/Linux), fallback to flask (Development/Windows)
    try:
        subprocess.run(["gunicorn", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("Using Gunicorn (Production Server)")
        cmd = ["gunicorn", "-c", "gunicorn_config.py", "app:app"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Gunicorn not found. Using Flask Development Server.")
        cmd = [sys.executable, FLASK_APP]

    p = subprocess.Popen(cmd, 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.STDOUT, 
                         universal_newlines=True)
    processes.append(p)
    return p

def start_nginx():
    print("Starting Nginx (Port 8080)...")
    conf_path = prepare_nginx_conf()
    
    # Always provide absolute prefix so relative paths in nginx.conf work
    cmd = [NGINX_EXECUTABLE, "-c", conf_path, "-p", os.path.abspath(".")]

    try:
        p = subprocess.Popen(cmd, 
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.STDOUT)
        processes.append(p)
        return p
    except FileNotFoundError:
        print(f"Error: {NGINX_EXECUTABLE} command not found. Please install Nginx.")
        sys.exit(1)

def cleanup(sig=None, frame=None):
    print("\nStopping Cloud Storage System...")
    
    # Stop Nginx
    try:
        conf_path = os.path.abspath(NGINX_PROD_CONF)
        subprocess.run([NGINX_EXECUTABLE, "-c", conf_path, "-s", "stop"], check=False)
        print("Nginx stopped.")
    except:
        pass
    
    # Remove runtime config
    if os.path.exists(NGINX_PROD_CONF):
        os.remove(NGINX_PROD_CONF)
    
    # Kill remaining processes
    for p in processes:
        try:
            p.terminate()
        except:
            pass
    
    print("Cleanup complete. Goodbye!")
    sys.exit(0)

if __name__ == "__main__":
    # Handle Ctrl+C
    signal.signal(signal.SIGINT, cleanup)

    try:
        # Pre-check and start
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
