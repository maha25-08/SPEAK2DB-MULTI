import requests
try:
    response = requests.get('http://127.0.0.1:11434/api/tags')
    if response.status_code == 200:
        models = response.json()
        print('✅ Ollama is running and accessible!')
        print('📦 Available models:')
        for model in models.get('models', []):
            print(f'  🤖 {model["name"]}')
    else:
        print(f'❌ Ollama returned status: {response.status_code}')
except Exception as e:
    print(f'❌ Error connecting to Ollama: {e}')
