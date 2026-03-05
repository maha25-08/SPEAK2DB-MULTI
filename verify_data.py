import requests
from bs4 import BeautifulSoup

# Test dashboard and extract actual data
session = requests.Session()

print('🔍 VERIFYING STUDENT DASHBOARD DATA')
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
    # Get dashboard
    print('2. Getting dashboard...')
    dashboard_response = session.get('http://127.0.0.1:5000/student-dashboard')
    print(f'   Dashboard Status: {dashboard_response.status_code}')
    
    if dashboard_response.status_code == 200:
        soup = BeautifulSoup(dashboard_response.text, 'html.parser')
        
        # Extract statistics
        stat_numbers = soup.find_all(class_='stat-number')
        print('\n📊 Dashboard Statistics:')
        for stat in stat_numbers:
            print(f'  - {stat.text.strip()}')
        
        # Check for actual data in tables
        current_books = soup.find(id='current-books')
        if current_books:
            book_cards = current_books.find_all(class_='book-card')
            print(f'\n📚 Current Books: {len(book_cards)} cards')
            
            # Extract book details
            for i, book_card in enumerate(book_cards[:3]):
                title_elem = book_card.find(class_='book-title')
                author_elem = book_card.find(class_='book-author')
                if title_elem and author_elem:
                    print(f'  Book {i+1}: {title_elem.text.strip()} by {author_elem.text.strip()}')
        
        history_section = soup.find(id='borrowing-history')
        if history_section:
            history_rows = history_section.find_all(class_='history-row')
            print(f'\n📚 Borrowing History: {len(history_rows)} rows')
            
            # Extract history details
            for i, row in enumerate(history_rows[:3]):
                cells = row.find_all('td')
                if len(cells) >= 3:
                    print(f'  History {i+1}: {cells[0].text.strip()} - {cells[1].text.strip()} - {cells[2].text.strip()}')
        
        fines_section = soup.find(id='fines')
        if fines_section:
            fine_cards = fines_section.find_all(class_='fine-card')
            print(f'\n💰 Fines: {len(fine_cards)} cards')
            
            # Extract fine details
            for i, fine_card in enumerate(fine_cards[:3]):
                amount_elem = fine_card.find(class_='fine-amount')
                status_elem = fine_card.find(class_='fine-status')
                if amount_elem and status_elem:
                    print(f'  Fine {i+1}: {amount_elem.text.strip()} ({status_elem.text.strip()})')
        
        # Check for empty states
        empty_states = soup.find_all(class_='empty-state')
        if empty_states:
            print(f'\n⚠️ Empty states found: {len(empty_states)}')
            for empty in empty_states:
                print(f'  - {empty.text.strip()}')
    else:
        print(f'   ❌ Dashboard failed: {dashboard_response.status_code}')
else:
    print(f'   ❌ Login failed: {login_response.status_code}')

print('\n🎯 Verification completed!')
