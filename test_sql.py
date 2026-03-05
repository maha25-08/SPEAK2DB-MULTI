import sqlite3

# Direct SQL test
print('🔍 DIRECT SQL TEST')
print('=' * 50)

try:
    conn = sqlite3.connect('library_main.db')
    cursor = conn.cursor()
    
    # Test simple query
    print('\n1. Testing simple student query...')
    cursor.execute('SELECT id, name, roll_number FROM Students WHERE roll_number = ?', ('MT3001',))
    student = cursor.fetchone()
    print(f'Student: {student}')
    
    if student:
        student_id = student[0]
        
        # Test issued books query
        print('\n2. Testing issued books query...')
        cursor.execute('SELECT COUNT(*) FROM Issued WHERE student_id = ?', (student_id,))
        count = cursor.fetchone()[0]
        print(f'Issued count: {count}')
        
        # Test with JOIN
        print('\n3. Testing JOIN query...')
        cursor.execute('''
            SELECT i.id, b.title, i.issue_date, i.return_date 
            FROM Issued i 
            JOIN Books b ON i.book_id = b.id 
            WHERE i.student_id = ?
            LIMIT 3
        ''', (student_id,))
        books = cursor.fetchall()
        print(f'Books with JOIN: {books}')
        
        # Test fines query
        print('\n4. Testing fines query...')
        cursor.execute('SELECT COUNT(*) FROM Fines WHERE student_id = ?', (student_id,))
        fine_count = cursor.fetchone()[0]
        print(f'Fines count: {fine_count}')
        
        if fine_count > 0:
            cursor.execute('SELECT * FROM Fines WHERE student_id = ? LIMIT 2', (student_id,))
            fines = cursor.fetchall()
            print(f'Fines data: {fines}')
    
    conn.close()
    print('\n✅ Direct SQL test completed!')
    
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
