import requests

# Test dashboard redirect
session = requests.Session()

# Login as MT3001
login_data = {'username': 'MT3001', 'password': 'pass'}
login_response = session.post('http://127.0.0.1:5000/login', data=login_data)
print(f'Login Status: {login_response.status_code}')

if login_response.status_code == 200:
    # Test dashboard redirect
    dashboard_response = session.get('http://127.0.0.1:5000/dashboard')
    print(f'Dashboard Redirect Status: {dashboard_response.status_code}')
    
    if dashboard_response.status_code == 200:
        # Check if it redirected to individual dashboard
        if 'Student 1' in dashboard_response.text and 'MT3001' in dashboard_response.text:
            print('✅ Successfully redirected to individual dashboard!')
        else:
            print('⚠️ Not redirected to individual dashboard')
        
        # Check for real data
        if 'Digital Electronics' in dashboard_response.text:
            print('✅ Real data found in dashboard!')
        else:
            print('⚠️ No real data found')
        
        # Extract statistics
        import re
        stat_numbers = re.findall(r'<div class="stat-number">(\d+)</div>', dashboard_response.text)
        print(f'Statistics: {stat_numbers}')
        
    else:
        print(f'❌ Dashboard redirect failed: {dashboard_response.status_code}')
else:
    print(f'❌ Login failed: {login_response.status_code}')
