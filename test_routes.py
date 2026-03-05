import requests

# Test all dashboard routes
routes = [
    'http://127.0.0.1:5000/student-dashboard',
    'http://127.0.0.1:5000/student/dashboard', 
    'http://127.0.0.1:5000/dashboard'
]

print("🔍 Testing Student Dashboard Routes")
print("=" * 50)

for route in routes:
    try:
        response = requests.get(route)
        print(f"✅ {route}: {response.status_code}")
        if response.status_code == 200:
            print(f"   Content length: {len(response.text)}")
            if 'student-dashboard' in response.text:
                print("   ✅ Dashboard template detected")
            else:
                print("   ⚠️ Different template returned")
        else:
            print(f"   ❌ Route failed")
    except Exception as e:
        print(f"❌ {route}: Error - {e}")

print("\n🎯 Test completed!")
