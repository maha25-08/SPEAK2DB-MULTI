import sqlite3
conn = sqlite3.connect('library_main.db')
cursor = conn.cursor()

# Check what role 'student' user has
cursor.execute('SELECT role FROM Users WHERE username = "student"')
user_role = cursor.fetchone()

if user_role:
    role = user_role[0]
    print(f'🎭 Current User Role: {role}')
    
    # Get permissions for this role
    cursor.execute('''
        SELECT p.permission_name 
        FROM Permissions p
        JOIN RolePermissions rp ON p.id = rp.permission_id
        JOIN Roles r ON rp.role_id = r.id
        WHERE r.role_name = ?
        ORDER BY p.permission_name
    ''', (role,))
    
    permissions = cursor.fetchall()
    print(f'📋 Permissions ({len(permissions)} total):')
    for perm in permissions[:10]:  # Show first 10
        print(f'  ✅ {perm[0]}')
    if len(permissions) > 10:
        print(f'  ... and {len(permissions) - 10} more')

conn.close()
