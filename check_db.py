import sqlite3

# Connect to database
conn = sqlite3.connect('library_main.db')
cursor = conn.cursor()

print('🔍 CHECKING DATABASE TABLES')
print('=' * 50)

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('Available tables:')
for table in tables:
    print(f'  - {table[0]}')

# Check if there's any data
print('\n📊 Table Contents:')
for table in tables:
    table_name = table[0]
    try:
        cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
        count = cursor.fetchone()[0]
        print(f'  {table_name}: {count} rows')
        
        # Show sample data if table has data
        if count > 0:
            cursor.execute(f'SELECT * FROM {table_name} LIMIT 3')
            sample_data = cursor.fetchall()
            print(f'    Sample data: {sample_data}')
    except Exception as e:
        print(f'  {table_name}: Error - {e}')

# Check specifically for student MT3001
print('\n👤 CHECKING STUDENT MT3001:')
cursor.execute('SELECT id, name, roll_number FROM Students WHERE roll_number = ?', ('MT3001',))
student = cursor.fetchone()
if student:
    print(f'✅ Student Found: ID={student[0]}, Name={student[1]}, Roll={student[2]}')
    student_id = student[0]
    
    # Check issued books for this student
    print('\n📚 Issued Books for MT3001:')
    cursor.execute('SELECT COUNT(*) FROM Issued WHERE student_id = ?', (student_id,))
    issued_count = cursor.fetchone()[0]
    print(f'Total issued records: {issued_count}')
    
    if issued_count > 0:
        cursor.execute('SELECT i.id, b.title, i.issue_date, i.return_date FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = ? LIMIT 5', (student_id,))
        issued_books = cursor.fetchall()
        for book in issued_books:
            return_status = book[3] if book[3] else 'Not returned'
            print(f'  - {book[1]} (Issued: {book[2]}, Returned: {return_status})')
    
    # Check fines for this student
    print('\n💰 Fines for MT3001:')
    cursor.execute('SELECT COUNT(*) FROM Fines WHERE student_id = ?', (student_id,))
    fines_count = cursor.fetchone()[0]
    print(f'Total fines: {fines_count}')
    
    if fines_count > 0:
        # Get column names first
        cursor.execute('PRAGMA table_info(Fines)')
        columns = [column[1] for column in cursor.fetchall()]
        print(f'  Fines columns: {columns}')
        
        cursor.execute('SELECT * FROM Fines WHERE student_id = ? LIMIT 3', (student_id,))
        fines = cursor.fetchall()
        for fine in fines:
            print(f'  - Fine data: {fine}')
else:
    print('❌ Student MT3001 not found!')

conn.close()
