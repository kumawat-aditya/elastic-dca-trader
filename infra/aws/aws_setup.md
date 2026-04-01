# ☁️ AWS Amazon Linux: Production Setup Guide

Since you are on **Amazon Linux** and want the **production** setup (built frontend files instead of development mode), here is the exact sequence of commands.

This guide assumes you are already logged into your EC2 terminal.

### Step 1: Install System Updates & Tools

Amazon Linux requires `yum` or `dnf` to install packages. We will install Git, Python, Node.js, and Screen (to keep servers running).

Run this block:

```bash
# Update system
sudo yum update -y

# Install Git, Python3, Pip, and Screen
sudo yum install git python3-pip screen -y

# Install Node.js (Amazon Linux specific setup for latest Node)
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo yum install nodejs -y

# Verify installations
node -v
python3 --version
```

---

### Step 2: Clone Your Repository

```bash
cd ~
git clone https://github.com/kumawat-aditya/elastic-dca-trader.git

# Enter the repository folder
cd elastic-dca-trader
```

---

### Step 3: Setup & Run Backend (Port 8000)

We will use a virtual environment and run the server using `screen` so it stays alive when you disconnect.

1.  **Navigate to the server folder:**

    ```bash
    cd apps/server
    ```

2.  **Install Dependencies:**

    ```bash
    # Create virtual environment
    python3 -m venv venv

    # Activate it
    source venv/bin/activate

    # Install requirements
    pip install -r requirements.txt
    ```

3.  **Start the Backend in Background:**

    ```bash
    # Create a screen session named "backend"
    screen -S backend

    # Run the engine
    python3 main.py
    ```

    _(You should see "Elastic DCA Engine v3.4.2" and "Uvicorn running on http://0.0.0.0:8000")_

4.  **Detach:** Press **`CTRL + A`**, then **`D`**.
    _(The backend is now running safely in the background)._

---

### Step 4: Setup & Run Frontend (Port 3000)

For production, we will **build** the optimized files and serve them using a lightweight static server.

1.  **Navigate to the web folder:**

    ```bash
    # Go up from server, then into web
    cd ../web
    ```

2.  **Install Dependencies:**

    ```bash
    npm install
    ```

3.  **Verify API URL (Crucial):**
    Since you cloned the repo, ensure your API service file points to your **AWS Public IP** (Elastic IP), not localhost.

    ```bash
    # Edit the API service file
    nano src/services/api.ts
    # also edit the websocekt connection
    nano src/App.tsx
    ```

    _Look for `const API_BASE_URL`. Change it to:_
    `const API_BASE_URL = "http://YOUR_AWS_IP:8000";`

    _Save: Press `Ctrl+O`, `Enter`. Exit: Press `Ctrl+X`._

4.  **Build for Production:**
    This compiles your React/TypeScript into optimized HTML/CSS/JS.

    ```bash
    npm run build
    ```

    _(This creates a `dist` folder)._

5.  **Serve the Build:**
    We will use `serve` (a simple static file server) to host the `dist` folder on port 3000.

    ```bash
    # Install 'serve' globally
    sudo npm install -g serve

    # Create screen session for frontend
    screen -S frontend

    # Serve the 'dist' folder on Port 3000
    ```

6.  **Detach:** Press **`CTRL + A`**, then **`D`**.

---

### Step 5: Access Your System

Everything is now running.

1.  Open your browser.
2.  Go to: **`http://YOUR_AWS_IP:3000`**

### Summary of Commands to Manage the App

- **To check Backend logs:** `screen -r backend`
- **To check Frontend logs:** `screen -r frontend`
- **To detach from screen:** `CTRL+A`, `D`
- **To kill a screen:** Inside the screen, press `CTRL+C`, then type `exit`.

### ⚙️. Maintenance Commands

Use these commands if you need to view logs or restart the bot.

| Action                     | Command                      |
| :------------------------- | :--------------------------- |
| **View running sessions**  | `screen -ls`                 |
| **Re-enter Backend logs**  | `screen -r backend`          |
| **Re-enter Frontend logs** | `screen -r frontend`         |
| **Stop Backend**           | `screen -X -S backend quit`  |
| **Stop Frontend**          | `screen -X -S frontend quit` |
| **Kill all sessions**      | `killall screen`             |

---
