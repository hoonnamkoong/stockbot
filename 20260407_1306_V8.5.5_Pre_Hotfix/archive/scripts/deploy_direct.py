import os
import subprocess

def load_env():
    env = {}
    if os.path.exists('.env.local'):
        with open('.env.local', 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    val = val.strip('"').strip("'")
                    env[key] = val
    return env

def deploy():
    env_vars = load_env()
    token = env_vars.get('VERCEL_OIDC_TOKEN')
    
    if not token:
        print("Error: VERCEL_OIDC_TOKEN not found in .env.local")
        return

    print(f"Deploying with token: {token[:10]}...")
    
    # Try using the token as --token argument
    # Note: OIDC token might need --scope or might be rejected if not a Personal Access Token.
    # But let's try.
    cmd = ["vercel", "deploy", "--prod", "--yes", "--token", token]
    
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print("Deployment Success!")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("Deployment Failed!")
        print(e.stderr)
        print(e.stdout)

if __name__ == "__main__":
    deploy()
