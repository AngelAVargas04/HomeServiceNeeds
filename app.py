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

@app.route('/browse/<int:service_id>')
def browse_providers(service_id):
    """Display verified providers and rates for one selected service category."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT ServiceID, ServiceName FROM S_Categories WHERE ServiceID = %s",
        (service_id,)
    )
    category = cursor.fetchone()

    if category is None:
        cursor.close()
        conn.close()
        flash("Service category not found.")
        return redirect(url_for('browse'))

    cursor.execute("""
        SELECT
            sr.RateID,
            sr.HourlyRate,
            pp.TravelR,
            u.UserID AS ProviderID,
            u.FullName AS ProviderName,
            u.Verified,
            ROUND(AVG(r.Rating), 1) AS AvgRating,
            COUNT(r.ReviewID) AS ReviewCount
        FROM S_Rates sr
        JOIN P_Profile pp ON sr.ProvID = pp.ProvID
        JOIN `User` u ON pp.ProvID = u.UserID
        LEFT JOIN Bookings b ON b.RateID = sr.RateID
        LEFT JOIN Reviews r ON r.BookingID = b.BookingID
        WHERE sr.ServiceID = %s
          AND u.Verified = 'Yes'
        GROUP BY
            sr.RateID,
            sr.HourlyRate,
            pp.TravelR,
            u.UserID,
            u.FullName,
            u.Verified
        ORDER BY sr.HourlyRate ASC
    """, (service_id,))

    providers = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'providers.html',
        category=category,
        providers=providers
    )

@app.route('/provider/<int:provider_id>/reviews')
def provider_reviews(provider_id):
    """Display all reviews for a selected provider."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            u.UserID,
            u.FullName,
            pp.TravelR,
            u.Verified
        FROM `User` u
        JOIN P_Profile pp ON u.UserID = pp.ProvID
        WHERE u.UserID = %s
    """, (provider_id,))

    provider = cursor.fetchone()

    if provider is None:
        cursor.close()
        conn.close()
        flash("Provider not found.")
        return redirect(url_for('browse'))

    cursor.execute("""
        SELECT
            r.ReviewID,
            r.Rating,
            r.Comment,
            b.Date,
            sc.ServiceName,
            client.FullName AS ClientName
        FROM Reviews r
        JOIN Bookings b ON r.BookingID = b.BookingID
        JOIN S_Rates sr ON b.RateID = sr.RateID
        JOIN S_Categories sc ON sr.ServiceID = sc.ServiceID
        JOIN `User` client ON b.ClientID = client.UserID
        WHERE sr.ProvID = %s
        ORDER BY b.Date DESC
    """, (provider_id,))

    reviews = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'provider_reviews.html',
        provider=provider,
        reviews=reviews
    )

@app.route('/book/<int:rate_id>', methods=['GET', 'POST'])
def book(rate_id):
    """Create a booking using a selected provider rate."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            sr.RateID,
            sr.HourlyRate,
            sc.ServiceName,
            u.FullName AS ProviderName
        FROM S_Rates sr
        JOIN S_Categories sc ON sr.ServiceID = sc.ServiceID
        JOIN P_Profile pp ON sr.ProvID = pp.ProvID
        JOIN `User` u ON pp.ProvID = u.UserID
        WHERE sr.RateID = %s
          AND u.Verified = 'Yes'
    """, (rate_id,))

    rate_info = cursor.fetchone()

    if rate_info is None:
        cursor.close()
        conn.close()
        flash("Provider rate not found or provider is not verified.")
        return redirect(url_for('browse'))

    cursor.execute("""
        SELECT u.UserID, u.FullName
        FROM `User` u
        LEFT JOIN P_Profile pp ON u.UserID = pp.ProvID
        WHERE pp.ProvID IS NULL
        ORDER BY u.FullName
    """)
    clients = cursor.fetchall()

    if request.method == 'POST':
        client_id = request.form.get('client_id')
        booking_date = request.form.get('booking_date')

        if not client_id or not booking_date:
            flash("Please select a client and booking date.")
            cursor.close()
            conn.close()
            return render_template('book.html', rate_info=rate_info, clients=clients)

        # HTML datetime-local uses T, MySQL DATETIME expects a space.
        booking_date = booking_date.replace("T", " ")
        if len(booking_date) == 16:
            booking_date += ":00"

        try:
            cursor.execute("""
                INSERT INTO Bookings (Status, ClientID, Date, RateID)
                VALUES (%s, %s, %s, %s)
            """, ("Pending", client_id, booking_date, rate_id))

            conn.commit()
            flash("Booking created successfully.")
            return redirect(url_for('bookings'))

        except mysql.connector.Error as err:
            conn.rollback()
            flash(f"Database error while creating booking: {err}")

    cursor.close()
    conn.close()

    return render_template('book.html', rate_info=rate_info, clients=clients)


@app.route('/bookings')
def bookings():
    """Display all bookings with client, provider, service, and rate information."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            b.BookingID,
            b.Status,
            b.Date,
            client.FullName AS ClientName,
            provider.FullName AS ProviderName,
            sc.ServiceName,
            sr.HourlyRate
        FROM Bookings b
        JOIN `User` client ON b.ClientID = client.UserID
        JOIN S_Rates sr ON b.RateID = sr.RateID
        JOIN P_Profile pp ON sr.ProvID = pp.ProvID
        JOIN `User` provider ON pp.ProvID = provider.UserID
        JOIN S_Categories sc ON sr.ServiceID = sc.ServiceID
        ORDER BY b.Date DESC
    """)

    all_bookings = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('bookings.html', bookings=all_bookings)


@app.route('/bookings/<int:booking_id>/update', methods=['POST'])
def update_booking(booking_id):
    """Update booking status using a controlled list of allowed statuses."""
    new_status = request.form.get('status')

    allowed_statuses = {"Pending", "Confirmed", "Completed", "Cancelled"}

    if new_status not in allowed_statuses:
        flash("Invalid booking status.")
        return redirect(url_for('bookings'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "UPDATE Bookings SET Status = %s WHERE BookingID = %s",
            (new_status, booking_id)
        )
        conn.commit()
        flash("Booking status updated.")

    except mysql.connector.Error as err:
        conn.rollback()
        flash(f"Database error while updating booking: {err}")

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('bookings'))

@app.route('/review/<int:booking_id>', methods=['GET', 'POST'])
def review(booking_id):
    """Allow a client to review a completed booking."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get booking details and make sure the booking exists
    cursor.execute("""
        SELECT
            b.BookingID,
            b.Status,
            b.Date,
            client.FullName AS ClientName,
            provider.FullName AS ProviderName,
            sc.ServiceName
        FROM Bookings b
        JOIN `User` client ON b.ClientID = client.UserID
        JOIN S_Rates sr ON b.RateID = sr.RateID
        JOIN P_Profile pp ON sr.ProvID = pp.ProvID
        JOIN `User` provider ON pp.ProvID = provider.UserID
        JOIN S_Categories sc ON sr.ServiceID = sc.ServiceID
        WHERE b.BookingID = %s
    """, (booking_id,))

    booking = cursor.fetchone()

    if booking is None:
        cursor.close()
        conn.close()
        flash("Booking not found.")
        return redirect(url_for('bookings'))

    # Only completed bookings can be reviewed
    if booking["Status"] != "Completed":
        cursor.close()
        conn.close()
        flash("Only completed bookings can be reviewed.")
        return redirect(url_for('bookings'))

    # Prevent duplicate reviews
    cursor.execute(
        "SELECT ReviewID FROM Reviews WHERE BookingID = %s",
        (booking_id,)
    )
    existing_review = cursor.fetchone()

    if existing_review:
        cursor.close()
        conn.close()
        flash("This booking already has a review.")
        return redirect(url_for('bookings'))

    if request.method == 'POST':
        rating = request.form.get('rating')
        comment = request.form.get('comment')

        if not rating:
            flash("Please select a rating.")
            cursor.close()
            conn.close()
            return render_template('review.html', booking=booking)

        try:
            rating = int(rating)

            if rating < 1 or rating > 5:
                flash("Rating must be between 1 and 5.")
                cursor.close()
                conn.close()
                return render_template('review.html', booking=booking)

            cursor.execute("""
                INSERT INTO Reviews (BookingID, Rating, Comment)
                VALUES (%s, %s, %s)
            """, (booking_id, rating, comment))

            conn.commit()
            flash("Review submitted successfully.")
            return redirect(url_for('bookings'))

        except mysql.connector.Error as err:
            conn.rollback()
            flash(f"Database error while submitting review: {err}")

        except ValueError:
            flash("Rating must be a number.")

    cursor.close()
    conn.close()

    return render_template('review.html', booking=booking)

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