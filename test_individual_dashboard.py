import requests

# Test individual dashboard
session = requests.Session()

# Login
login_data = {'username': 'MT3001', 'password': 'pass'}
login_response = session.post('http://127.0.0.1:5000/login', data=login_data)
print(f'Login Status: {login_response.status_code}')

if login_response.status_code == 200:
    # Get individual dashboard
    dashboard_response = session.get('http://127.0.0.1:5000/student-dashboard-individual')
    print(f'Individual Dashboard Status: {dashboard_response.status_code}')
    
    if dashboard_response.status_code == 200:
        # Check for actual data
        if 'Digital Electronics' in dashboard_response.text:
            print('✅ Found book data in individual dashboard!')
        else:
            print('⚠️ No book data found')
        
        # Check for statistics
        if 'stat-number' in dashboard_response.text:
            print('✅ Statistics found in dashboard')
        else:
            print('⚠️ No statistics found')
        
        # Check for non-zero values
        if '0' in dashboard_response.text and dashboard_response.text.count('0') > 5:
            print('⚠️ Still showing zeros')
        else:
            print('✅ Real data found!')
        
        # Extract some sample data
        import re
        stat_numbers = re.findall(r'<div class="stat-number">(\d+)</div>', dashboard_response.text)
        print(f'Statistics: {stat_numbers}')
        
        book_titles = re.findall(r'<h3 class="book-title">([^<]+)</h3>', dashboard_response.text)
        print(f'Books found: {len(book_titles)}')
        if book_titles:
            print(f'Sample books: {book_titles[:3]}')
        
    else:
        print(f'❌ Dashboard failed: {dashboard_response.status_code}')
        print(f'Error: {dashboard_response.text[:200]}')
else:
    print(f'❌ Login failed: {login_response.status_code}')
