#!/bin/bash

# Ryuk AI Installation Script
# Automates the setup of system dependencies, python environment, and AI models.

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}             Ryuk AI - Installation Script          ${NC}"
echo -e "${GREEN}====================================================${NC}"

# 1. System Dependency Checks
echo -e "\n${GREEN}[1/6] Checking system requirements...${NC}"

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION=$VERSION_CODENAME
else
    echo -e "${RED}Error: Cannot detect OS. /etc/os-release missing.${NC}"
    exit 1
fi

echo -e "Detected OS: $NAME ($VERSION)"

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 is not installed.${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo -e "Found Python $PYTHON_VERSION"

# Check for pip
if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
    echo -e "${RED}Error: pip is not installed. Please install python3-pip.${NC}"
    exit 1
fi

# Check for venv module
if ! python3 -m venv --help &> /dev/null; then
    echo -e "${RED}Error: python3-venv is missing. Install it with: sudo apt install python3-venv${NC}"
    exit 1
fi

# 2. Virtual Environment Setup
echo -e "\n${GREEN}[2/6] Setting up virtual environment...${NC}"
if [ -d "venv" ]; then
    echo -e "Virtual environment 'venv' already exists. Skipping creation."
else
    python3 -m venv venv
    echo -e "Created 'venv' directory."
fi

# 3. Installing Python Packages
echo -e "\n${GREEN}[3/6] Installing Python dependencies...${NC}"
source venv/bin/activate
pip install --upgrade pip

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo -e "${RED}Error: requirements.txt not found!${NC}"
    exit 1
fi

# 4. Infrastructure Installation (Redis & MongoDB)
echo -e "\n${GREEN}[4/6] Verifying/Installing Infrastructure Services...${NC}"

# Function to install Redis
install_redis() {
    echo -e "${YELLOW}Redis missing. Attempting installation...${NC}"
    if [[ "$OS" == "ubuntu" || "$OS" == "debian" ]]; then
        sudo apt-get update
        sudo apt-get install -y redis-server
        sudo systemctl enable redis-server
        sudo systemctl start redis-server
    else
        echo -e "${RED}Automatic Redis installation not supported for $OS. Please install manually.${NC}"
    fi
}

# Function to install MongoDB
install_mongodb() {
    echo -e "${YELLOW}MongoDB missing. Attempting installation...${NC}"
    if [[ "$OS" == "ubuntu" ]]; then
        sudo apt-get install -y gnupg curl
        curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | sudo gpg --dearmor -o /usr/share/keyrings/mongodb-server-8.0.gpg --yes
        
        # Add repository based on version
        if [[ "$VERSION" == "noble" ]]; then
            echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
        elif [[ "$VERSION" == "jammy" ]]; then
             echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
        else
            echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
        fi
        
        sudo apt-get update
        sudo apt-get install -y mongodb-org
        sudo systemctl enable mongod
        sudo systemctl start mongod
    else
        echo -e "${RED}Automatic MongoDB installation not supported for $OS. Please install manually.${NC}"
    fi
}

# Redis check and install
if ! command -v redis-server &> /dev/null; then
    install_redis
fi

if systemctl is-active --quiet redis-server; then
    echo -e "Redis is running."
else
    echo -e "${YELLOW}Starting Redis...${NC}"
    sudo systemctl start redis-server
fi

# MongoDB check and install
if ! command -v mongod &> /dev/null; then
    install_mongodb
fi

if systemctl is-active --quiet mongod; then
    echo -e "MongoDB is running."
else
    echo -e "${YELLOW}Starting MongoDB...${NC}"
    sudo systemctl start mongod
fi

# 5. Model Downloading
echo -e "\n${GREEN}[5/6] Pre-downloading InsightFace models (buffalo_l)...${NC}"
python3 << END
import os
import warnings
warnings.filterwarnings("ignore")
try:
    from insightface.app import FaceAnalysis
    print("Initializing model to trigger download...")
    # This will download models to ~/.insightface/models/
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("\nModel assets verified/downloaded successfully.")
except Exception as e:
    print(f"\nError during model download: {e}")
    print("You may need to download models manually or check your internet connection.")
END

# 6. Environment Configuration
echo -e "\n${GREEN}[6/6] Finalizing configuration...${NC}"
if [ ! -f ".env" ]; then
    echo -e "Setting up .env file..."
    
    # Prompt for Gemini API Key (Optional)
    echo -e "\n${YELLOW}Optional: Gemini AI Intelligence Feature${NC}"
    echo -e "The Gemini API key is used for generating autonomous tactical reports."
    echo -n "Enter your GEMINI_API_KEY (or press Enter to skip): "
    read GEMINI_KEY

    echo "# Ryuk AI Configuration" > .env
    if [ -z "$GEMINI_KEY" ]; then
        echo -e "${YELLOW}Skipping Gemini API key. You can add it later in the .env file.${NC}"
        echo "GEMINI_API_KEY=your_api_key_here" >> .env
    else
        echo "GEMINI_API_KEY=$GEMINI_KEY" >> .env
        echo -e "${GREEN}Gemini API key saved.${NC}"
    fi

    echo "MONGO_URI=mongodb://localhost:27017" >> .env
    echo "REDIS_HOST=localhost" >> .env
    echo -e ".env file created with defaults."
else
    echo -e ".env file already exists."
fi

echo -e "\n${GREEN}====================================================${NC}"
echo -e "${GREEN}            Installation Finished Successfully!      ${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "\nTo start the application:"
echo -e "1. ${YELLOW}source venv/bin/activate${NC}"
echo -e "2. ${YELLOW}python main.py${NC}"
echo -e "\nNote: Services (Redis & MongoDB) have been started and enabled."
