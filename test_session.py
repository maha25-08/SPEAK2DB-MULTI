import requests

# Test session handling
session = requests.Session()

print('🔍 TESTING SESSION HANDLING')
print('=' * 50)

# Login
login_data = {
    'username': 'MT3001',
    'password': 'pass'
}

print('1. Logging in...')
login_response = session.post('http://127.0.0.1:5000/login', data=login_data)
print(f'   Login Status: {login_response.status_code}')

if login_response.status_code == 200:
    print('2. Getting dashboard...')
    dashboard_response = session.get('http://127.0.0.1:5000/student-dashboard')
    print(f'   Dashboard Status: {dashboard_response.status_code}')
    
    if dashboard_response.status_code == 200:
        # Check if we're redirected (session issue)
        if 'student-dashboard' in dashboard_response.url:
            print('   ✅ Dashboard loaded successfully')
        else:
            print('   ⚠️ Redirected - possible session issue')
            
        # Check if dashboard contains debug info
        if '[DEBUG]' in dashboard_response.text:
            print('   ✅ Debug logs found in response')
        else:
            print('   ⚠️ No debug logs found')
            
        # Check for zero values
        if '0' in dashboard_response.text and dashboard_response.text.count('0') > 5:
            print('   ⚠️ Multiple zeros detected - data issue')
        elif 'No data available' in dashboard_response.text:
            print('   ✅ No data messages found')
        else:
            print('   📊 Checking for actual data...')
            
            # Look for specific data patterns
            if 'Digital Electronics' in dashboard_response.text:
                print('   ✅ Book data found!')
            elif '833.0' in dashboard_response.text:
                print('   ✅ Fine data found!')
            else:
                print('   ❌ No specific data patterns found')
    else:
        print(f'   ❌ Dashboard failed: {dashboard_response.status_code}')
else:
    print(f'   ❌ Login failed: {login_response.status_code}')

print('\n🎯 Session test completed!')
