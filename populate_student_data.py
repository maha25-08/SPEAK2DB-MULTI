import sqlite3
import random
from datetime import datetime, timedelta

def populate_student_data():
    """Populate realistic data for all students"""
    
    # Connect to database
    conn = sqlite3.connect('library_main.db')
    cursor = conn.cursor()
    
    print('🎯 POPULATING REALISTIC STUDENT DATA')
    print('=' * 50)
    
    # Get all students
    cursor.execute("SELECT id, name, roll_number FROM Students")
    students = cursor.fetchall()
    print(f'Found {len(students)} students')
    
    # Sample book data
    books = [
        (1, "Digital Electronics", "Morris Mano", "978-0133429401"),
        (2, "Data Structures and Algorithms", "Cormen", "978-0262033848"),
        (3, "Operating Systems", "Silberschatz", "978-0073526255"),
        (4, "Database Management Systems", "Ramakrishnan", "978-0072934634"),
        (5, "Computer Networks", "Tanenbaum", "978-0133587933"),
        (6, "Software Engineering", "Pressman", "978-0073398134"),
        (7, "Artificial Intelligence", "Russell", "978-0136042597"),
        (8, "Machine Learning", "Mitchell", "978-0073528272"),
        (9, "Cloud Computing", "Buyya", "978-0133588285"),
        (10, "Cybersecurity", "Stallings", "978-0133588282")
    ]
    
    # Sample fine reasons
    fine_reasons = [
        "Late Return", "Lost Book", "Damaged Book", "Overdue Fine", 
        "Library Policy Violation", "Noise Complaint", "Unauthorized Use"
    ]
    
    # Sample reservation requests
    book_requests = [
        "High Demand Book", "New Release", "Research Material", 
        "Reference Book", "Study Guide", "Exam Preparation"
    ]
    
    try:
        # Clear existing data
        print('\n🗑️ Clearing existing data...')
        cursor.execute("DELETE FROM Issued")
        cursor.execute("DELETE FROM Fines")
        cursor.execute("DELETE FROM Reservations")
        conn.commit()
        
        # Populate data for each student
        for i, (student_id, name, roll_number) in enumerate(students, 1):
            print(f'\n📚 Processing Student {i}: {name} ({roll_number})')
            
            # Generate realistic borrowing history (5-15 books per student)
            num_books = random.randint(8, 15)
            issued_books = []
            
            for j in range(num_books):
                book_id = random.randint(1, 10)
                book = next((b for b in books if b[0] == book_id), None)
                
                if book:
                    # Random issue date (last 6 months)
                    issue_date = datetime.now() - timedelta(days=random.randint(1, 180))
                    
                    # 70% chance book is returned
                    if random.random() < 0.7:
                        return_date = issue_date + timedelta(days=random.randint(7, 30))
                    else:
                        return_date = None
                    
                    issued_books.append((
                        student_id,  # student_id
                        book_id,  # book_id  
                        issue_date.strftime("%Y-%m-%d"),  # issue_date
                        return_date.strftime("%Y-%m-%d") if return_date else None,  # return_date
                        random.randint(1, 3)  # id (will be auto-generated)
                    ))
            
            # Insert issued books
            if issued_books:
                cursor.executemany("""
                    INSERT INTO Issued (student_id, book_id, issue_date, return_date, due_date)
                    VALUES (?, ?, ?, ?, ?)
                """, [(book[0], book[1], book[2], book[3], book[4]) for book in issued_books])
                print(f'  ✅ Added {len(issued_books)} borrowing records')
            
            # Generate current borrowed books (2-4 books per student)
            num_current = random.randint(2, 5)
            current_books = []
            
            for j in range(num_current):
                book_id = random.randint(1, 10)
                book = next((b for b in books if b[0] == book_id), None)
                
                if book:
                    issue_date = datetime.now() - timedelta(days=random.randint(1, 60))
                    due_date = datetime.now() + timedelta(days=random.randint(10, 30))
                    
                    current_books.append((
                        student_id,  # student_id
                        book_id,  # book_id
                        issue_date.strftime("%Y-%m-%d"),  # issue_date
                        None,  # return_date (current books)
                        due_date.strftime("%Y-%m-%d"),  # due_date
                        random.randint(1, 3)  # id (will be auto-generated)
                    ))
            
            # Insert current books
            if current_books:
                cursor.executemany("""
                    INSERT INTO Issued (student_id, book_id, issue_date, return_date, due_date)
                    VALUES (?, ?, ?, ?, ?)
                """, [(book[0], book[1], book[2], book[3], book[4]) for book in current_books])
                print(f'  ✅ Added {len(current_books)} current borrowed books')
            
            # Generate fines (2-6 fines per student)
            num_fines = random.randint(2, 6)
            fines = []
            
            for j in range(num_fines):
                fine_amount = random.randint(50, 500)
                fine_type = random.choice(fine_reasons)
                issue_date = datetime.now() - timedelta(days=random.randint(1, 90))
                
                # 60% chance fine is unpaid
                status = "Unpaid" if random.random() < 0.6 else "Paid"
                payment_date = None
                if status == "Paid":
                    payment_date = issue_date + timedelta(days=random.randint(1, 30))
                
                fines.append((
                    student_id,  # student_id
                    fine_amount,  # fine_amount
                    fine_type,  # fine_type
                    status,  # status
                    issue_date.strftime("%Y-%m-%d"),  # issue_date
                    None,  # payment_date (column doesn't exist)
                    random.randint(1, 3)  # id (will be auto-generated)
                ))
            
            # Insert fines
            if fines:
                cursor.executemany("""
                    INSERT INTO Fines (student_id, fine_amount, fine_type, status, issue_date)
                    VALUES (?, ?, ?, ?, ?)
                """, [(fine[0], fine[1], fine[2], fine[3], fine[4]) for fine in fines])
                print(f'  ✅ Added {len(fines)} fine records')
            
            # Generate book requests/reservations (1-4 per student)
            num_requests = random.randint(1, 4)
            reservations = []
            
            for j in range(num_requests):
                book_id = random.randint(1, 10)
                book = next((b for b in books if b[0] == book_id), None)
                request_type = random.choice(book_requests)
                reservation_date = datetime.now() - timedelta(days=random.randint(1, 30))
                
                if book:
                    reservations.append((
                        student_id,  # student_id
                        book_id,  # book_id
                        reservation_date.strftime("%Y-%m-%d"),  # reservation_date
                        random.randint(1, 3)  # id (will be auto-generated)
                    ))
            
            # Insert reservations
            if reservations:
                cursor.executemany("""
                    INSERT INTO Reservations (student_id, book_id, reservation_date)
                    VALUES (?, ?, ?)
                """, [(reservation[0], reservation[1], reservation[2]) for reservation in reservations])
                print(f'  ✅ Added {len(reservations)} book requests')
            
            conn.commit()
            print(f'  🎉 Completed Student {i}: {name}')
        
        # Commit all changes
        conn.commit()
        print('\n✅ DATA POPULATION COMPLETED!')
        
        # Show summary
        print('\n📊 SUMMARY:')
        cursor.execute("SELECT COUNT(*) FROM Issued")
        total_issued = cursor.fetchone()[0]
        print(f'  Total Issued Records: {total_issued}')
        
        cursor.execute("SELECT COUNT(*) FROM Fines")
        total_fines = cursor.fetchone()[0]
        print(f'  Total Fine Records: {total_fines}')
        
        cursor.execute("SELECT COUNT(*) FROM Reservations")
        total_reservations = cursor.fetchone()[0]
        print(f'  Total Reservation Records: {total_reservations}')
        
    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    populate_student_data()
