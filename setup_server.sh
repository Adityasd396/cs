#!/bin/bash

# CloudStream Server Setup Script for Linux (Ubuntu/Debian/Amazon Linux)
# This script automates the installation of dependencies and sets correct permissions.

echo "==========================================="
echo "   CloudStream Server Setup Automation     "
echo "==========================================="

# 1. Detect OS and install system dependencies
if [ -f /etc/debian_version ]; then
    echo "[1/4] Installing system dependencies (Apt)..."
    sudo apt update
    sudo apt install -y python3-pip python3-venv nginx ffmpeg git
elif [ -f /etc/amazon-linux-release ] || [ -f /etc/redhat-release ]; then
    echo "[1/4] Installing system dependencies (Yum/Dnf)..."
    sudo yum update -y
    sudo yum install -y python3-pip nginx ffmpeg git
else
    echo "Unsupported OS for automatic install. Please install python3, nginx, and ffmpeg manually."
fi

# 2. Setup Python Virtual Environment
echo "[2/4] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# 3. Create required directories and set permissions
echo "[3/4] Configuring directories and permissions..."
mkdir -p uploads hls logs temp static/js static/css
sudo chown -R $USER:www-data .
chmod -R 775 uploads hls logs temp

# 4. Final instructions
echo "[4/4] Setup complete!"
echo "-------------------------------------------"
echo "To start the system on Linux or Windows:"
echo "1. Activate environment: source venv/bin/activate (Linux) or .\venv\Scripts\activate (Windows)"
echo "2. Run launcher: python start.py"
echo "-------------------------------------------"
echo "NOTE: This system is designed to be universal."
echo "The 'start.py' script handles Nginx configuration"
echo "and Flask/Gunicorn startup automatically for both platforms."
echo "==========================================="
