from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector
import os
from dotenv import load_dotenv

# Load the hidden variables from the .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = 'home_needs_secret_key' 

# AWS RDS Connection Configuration
db_config = {
    'host': 'database-1.cwjkoeyeihte.us-east-1.rds.amazonaws.com',
    'user': 'angel26',
    'password': os.environ.get('DB_PASSWORD'), # securely fetches the password!
    'database': 'HomeNeedsService'
}

def get_db_connection():
    """Establishes and returns a connection to the AWS RDS instance."""
    return mysql.connector.connect(**db_config)

# --- ROUTES ---

@app.route('/')
def index():
    """The main landing page."""
    return render_template('index.html')

@app.route('/browse')
def browse():
    """Fetches service categories from the database and displays them."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Fetch all available categories
    cursor.execute("SELECT * FROM S_Categories")
    all_categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # Pass the categories list to the HTML template
    return render_template('browse.html', categories=all_categories)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles the user registration form and database insertion."""
    if request.method == 'POST':
        full_name = request.form['fullname']
        
        # Connect to AWS Database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Insert the new user. 'Verified' defaults to 'No' per the schema design.
            sql = "INSERT INTO User (FullName, Verified) VALUES (%s, %s)"
            cursor.execute(sql, (full_name, 'No'))
            conn.commit() # Save the changes to the cloud
            
            flash('Registration successful! Your account is pending admin verification.')
            return redirect(url_for('users'))
            
        except mysql.connector.Error as err:
            flash(f'Database Error: {err}')
            
        finally:
            # Always close the connection to prevent overloading the AWS server
            cursor.close()
            conn.close()
            
    # If it's a GET request, just show the form
    return render_template('register.html')

@app.route('/users')
def users():
    """Fetches and displays all registered users from the database."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True) # Returns rows as easy-to-read dictionaries
    
    cursor.execute("SELECT * FROM User")
    all_users = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('users.html', users=all_users)

if __name__ == '__main__':
    # Runs the local development server
    app.run(debug=True)