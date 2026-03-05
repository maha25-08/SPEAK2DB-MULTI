import requests
from bs4 import BeautifulSoup

# Test dashboard with student login
session = requests.Session()

# First login
login_data = {
    'username': 'MT3001',
    'password': 'pass'
}

print('🔍 TESTING STUDENT DASHBOARD DATA')
print('=' * 50)

# Login
login_response = session.post('http://127.0.0.1:5000/login', data=login_data)
print(f'Login Status: {login_response.status_code}')

if login_response.status_code == 200:
    # Get dashboard
    dashboard_response = session.get('http://127.0.0.1:5000/student-dashboard')
    print(f'Dashboard Status: {dashboard_response.status_code}')
    
    if dashboard_response.status_code == 200:
        soup = BeautifulSoup(dashboard_response.text, 'html.parser')
        
        # Extract statistics
        stat_numbers = soup.find_all(class_='stat-number')
        print('\n📊 Dashboard Statistics:')
        for stat in stat_numbers:
            print(f'  - {stat.text.strip()}')
        
        # Check for data in tables
        current_books = soup.find(id='current-books')
        if current_books:
            book_cards = current_books.find_all(class_='book-card')
            print(f'\n📚 Current Books: {len(book_cards)} cards')
        
        history_section = soup.find(id='borrowing-history')
        if history_section:
            history_rows = history_section.find_all(class_='history-row')
            print(f'📚 Borrowing History: {len(history_rows)} rows')
        
        fines_section = soup.find(id='fines')
        if fines_section:
            fine_cards = fines_section.find_all(class_='fine-card')
            print(f'💰 Fines: {len(fine_cards)} cards')
            
            # Show fine details
            for fine_card in fine_cards[:2]:
                amount = fine_card.find(class_='fine-amount')
                status = fine_card.find(class_='fine-status')
                if amount and status:
                    print(f'  - {amount.text.strip()} ({status.text.strip()})')
        
        requests_section = soup.find(id='requests')
        if requests_section:
            request_cards = requests_section.find_all(class_='request-card')
            print(f'📋 Book Requests: {len(request_cards)} cards')
    else:
        print(f'❌ Dashboard failed: {dashboard_response.status_code}')
else:
    print(f'❌ Login failed: {login_response.status_code}')

print('\n🎯 Test completed!')
