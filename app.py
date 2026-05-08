from flask import Flask, render_template, request, redirect, url_for, flash, session
import mysql.connector
import os
from dotenv import load_dotenv

# Load the hidden variables from the .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_fallback_secret")

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

def delete_user_and_related_records(cursor, user_id):
    """
    Deletes a user and all related service, booking, and review data.
    Handles both client-side bookings and provider-side service records.
    """

    # Delete reviews connected to bookings where this user is the client
    # OR this user is the provider connected to the booking rate.
    cursor.execute("""
        DELETE r
        FROM Reviews r
        JOIN Bookings b ON r.BookingID = b.BookingID
        LEFT JOIN S_Rates sr ON b.RateID = sr.RateID
        WHERE b.ClientID = %s OR sr.ProvID = %s
    """, (user_id, user_id))

    # Delete bookings where this user is the client
    # OR this user is the provider connected to the booking rate.
    cursor.execute("""
        DELETE b
        FROM Bookings b
        LEFT JOIN S_Rates sr ON b.RateID = sr.RateID
        WHERE b.ClientID = %s OR sr.ProvID = %s
    """, (user_id, user_id))

    # Delete provider service rates.
    cursor.execute(
        "DELETE FROM S_Rates WHERE ProvID = %s",
        (user_id,)
    )

    # Delete provider profile.
    cursor.execute(
        "DELETE FROM P_Profile WHERE ProvID = %s",
        (user_id,)
    )

    # Delete user account.
    cursor.execute(
        "DELETE FROM `User` WHERE UserID = %s",
        (user_id,)
    )

@app.before_request
def require_login():
    """Require users to log in before using the site."""
    open_routes = {"login", "register", "static"}

    if request.endpoint in open_routes or request.endpoint is None:
        return

    if "user_id" not in session:
        return redirect(url_for("login"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Prototype login using an existing full name from the User table."""
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()

        if not full_name:
            flash("Please enter your full name.")
            return redirect(url_for('login'))

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT UserID, FullName FROM `User` WHERE LOWER(FullName) = LOWER(%s)",
            (full_name,)
        )
        matches = cursor.fetchall()

        cursor.close()
        conn.close()

        if len(matches) == 0:
            flash("No user exists under that name. Try again or sign up.")
            return redirect(url_for('login'))

        if len(matches) > 1:
            flash("More than one account uses that name. Please contact an admin or use a unique name.")
            return redirect(url_for('login'))

        user = matches[0]

        session["user_id"] = user["UserID"]
        session["full_name"] = user["FullName"]

        flash(f"Logged in as {user['FullName']}.")
        return redirect(url_for('index'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    """Clear the current user session."""
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('login'))

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    """Simple admin access control using an admin code from .env."""
    if request.method == 'POST':
        admin_code = request.form.get('admin_code', '')
        expected_code = os.environ.get("ADMIN_CODE")

        if not expected_code:
            flash("Admin code is not configured.")
            return redirect(url_for("admin_login"))

        if admin_code == expected_code:
            session["is_admin"] = True
            flash("Admin access granted.")
            return redirect(url_for("users"))

        flash("Invalid admin code.")
        return redirect(url_for("admin_login"))

    return render_template("admin_login.html")


@app.route('/admin-logout')
def admin_logout():
    """Remove admin access only."""
    session.pop("is_admin", None)
    flash("Admin access removed.")
    return redirect(url_for("index"))

@app.route('/account')
def account_redirect():
    """Send the logged-in user to their own account page."""
    return redirect(url_for('account', user_id=session["user_id"]))

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
            sql = "INSERT INTO `User` (FullName, Verified) VALUES (%s, %s)"
            cursor.execute(sql, (full_name, 'No'))
            new_user_id = cursor.lastrowid # Get the auto-generated UserID for the new user
            conn.commit() # Save the changes to the cloud
            
            session["user_id"] = new_user_id
            session["full_name"] = full_name

            flash('Registration successful. You are now logged in.')
            return redirect(url_for('index'))
            
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
    """Admin dashboard for registered users."""

    if not session.get("is_admin"):
        flash("Admin access required.")
        return redirect(url_for("admin_login"))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True) # Returns rows as easy-to-read dictionaries
    
    cursor.execute("SELECT * FROM `User`")
    all_users = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('users.html', users=all_users)

@app.route('/users/<int:user_id>/verify', methods=['POST'])
def update_user_verification(user_id):
    if not session.get("is_admin"):
        flash("Admin access required.")
        return redirect(url_for("admin_login"))
    """Update a user's verification status."""
    verified_status = request.form.get('verified')

    if verified_status not in ["Yes", "No"]:
        flash("Invalid verification status.")
        return redirect(url_for('users'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "UPDATE `User` SET Verified = %s WHERE UserID = %s",
            (verified_status, user_id)
        )
        conn.commit()
        flash("User verification status updated.")

    except mysql.connector.Error as err:
        conn.rollback()
        flash(f"Database Error: {err}")

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('users'))

@app.route('/users/<int:user_id>/delete', methods=['GET', 'POST'])
def admin_delete_user(user_id):
    if not session.get("is_admin"):
        flash("Admin access required.")
        return redirect(url_for("admin_login"))
    """Allow admin/user dashboard to delete a selected account."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT UserID, FullName FROM `User` WHERE UserID = %s",
        (user_id,)
    )
    user = cursor.fetchone()

    if user is None:
        cursor.close()
        conn.close()
        flash("User account not found.")
        return redirect(url_for("users"))

    if request.method == 'POST':
        try:
            delete_user_and_related_records(cursor, user_id)
            conn.commit()

            cursor.close()
            conn.close()

            if session.get("user_id") == user_id:
                session.clear()
                flash("Account deleted. You have been logged out.")
                return redirect(url_for("login"))

            flash("User account and related records were deleted.")
            return redirect(url_for("users"))

        except mysql.connector.Error as err:
            conn.rollback()
            flash(f"Database Error while deleting user: {err}")

    cursor.close()
    conn.close()

    return render_template(
        "delete_account.html",
        user=user,
        delete_mode="admin"
    )

@app.route('/account/<int:user_id>', methods=['GET', 'POST'])
def account(user_id):
    if session.get("user_id") != user_id:
        flash("You can only access your own account page.")
        return redirect(url_for("account", user_id=session["user_id"]))
    """User account page. Verified users can add provider service information."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT UserID, FullName, Verified FROM `User` WHERE UserID = %s",
        (user_id,)
    )
    user = cursor.fetchone()

    if user is None:
        cursor.close()
        conn.close()
        flash("User account not found.")
        return redirect(url_for('users'))

    cursor.execute("SELECT ServiceID, ServiceName FROM S_Categories ORDER BY ServiceName")
    services = cursor.fetchall()

    cursor.execute(
        "SELECT ProvID, TravelR FROM P_Profile WHERE ProvID = %s",
        (user_id,)
    )
    provider_profile = cursor.fetchone()

    cursor.execute("""
        SELECT
            sr.RateID,
            sr.HourlyRate,
            sc.ServiceName
        FROM S_Rates sr
        JOIN S_Categories sc ON sr.ServiceID = sc.ServiceID
        WHERE sr.ProvID = %s
        ORDER BY sc.ServiceName
    """, (user_id,))
    provider_services = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'account.html',
        user=user,
        services=services,
        provider_profile=provider_profile,
        provider_services=provider_services
    )

@app.route('/account/delete', methods=['GET', 'POST'])
def delete_own_account():
    """Allow the logged-in user to delete their own account."""
    user_id = session.get("user_id")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT UserID, FullName FROM `User` WHERE UserID = %s",
        (user_id,)
    )
    user = cursor.fetchone()

    if user is None:
        cursor.close()
        conn.close()
        session.clear()
        flash("Account no longer exists.")
        return redirect(url_for("login"))

    if request.method == 'POST':
        try:
            delete_user_and_related_records(cursor, user_id)
            conn.commit()

            cursor.close()
            conn.close()

            session.clear()
            flash("Your account and related records were deleted.")
            return redirect(url_for("login"))

        except mysql.connector.Error as err:
            conn.rollback()
            flash(f"Database Error while deleting account: {err}")

    cursor.close()
    conn.close()

    return render_template(
        "delete_account.html",
        user=user,
        delete_mode="self"
    )

@app.route('/account/<int:user_id>/provider-service', methods=['POST'])
def add_provider_service(user_id):
    """Allow a verified user to add or update provider service/rate information."""
    travel_radius = request.form.get('travel_radius')
    service_id = request.form.get('service_id')
    hourly_rate = request.form.get('hourly_rate')

    if not travel_radius or not service_id or not hourly_rate:
        flash("Travel radius, service, and hourly rate are required.")
        return redirect(url_for('account', user_id=user_id))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT UserID, Verified FROM `User` WHERE UserID = %s",
            (user_id,)
        )
        user = cursor.fetchone()

        if user is None:
            flash("User account not found.")
            return redirect(url_for('users'))

        if user["Verified"] != "Yes":
            flash("Only verified users can add provider services.")
            return redirect(url_for('account', user_id=user_id))

        travel_radius = int(travel_radius)
        hourly_rate = float(hourly_rate)

        if travel_radius <= 0:
            flash("Travel radius must be greater than 0.")
            return redirect(url_for('account', user_id=user_id))

        if hourly_rate <= 0:
            flash("Hourly rate must be greater than 0.")
            return redirect(url_for('account', user_id=user_id))

        # Create provider profile if it does not exist.
        cursor.execute(
            "SELECT ProvID FROM P_Profile WHERE ProvID = %s",
            (user_id,)
        )
        existing_profile = cursor.fetchone()

        if existing_profile:
            cursor.execute(
                "UPDATE P_Profile SET TravelR = %s WHERE ProvID = %s",
                (travel_radius, user_id)
            )
        else:
            cursor.execute(
                "INSERT INTO P_Profile (ProvID, TravelR) VALUES (%s, %s)",
                (user_id, travel_radius)
            )

        # Avoid duplicate rates for the same provider/service.
        cursor.execute(
            "SELECT RateID FROM S_Rates WHERE ProvID = %s AND ServiceID = %s",
            (user_id, service_id)
        )
        existing_rate = cursor.fetchone()

        if existing_rate:
            cursor.execute(
                "UPDATE S_Rates SET HourlyRate = %s WHERE RateID = %s",
                (hourly_rate, existing_rate["RateID"])
            )
            flash("Provider service updated successfully.")
        else:
            cursor.execute(
                "INSERT INTO S_Rates (ProvID, ServiceID, HourlyRate) VALUES (%s, %s, %s)",
                (user_id, service_id, hourly_rate)
            )
            flash("Provider service added successfully.")

        conn.commit()

    except ValueError:
        conn.rollback()
        flash("Travel radius and hourly rate must be valid numbers.")

    except mysql.connector.Error as err:
        conn.rollback()
        flash(f"Database Error: {err}")

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('account', user_id=user_id))

if __name__ == '__main__':
    # Runs the local development server
    app.run(debug=True)