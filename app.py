from flask import Flask, render_template
import mysql.connector

app = Flask(__name__)

# Basic route to check implementation
@app.route('/')
def home():
    return "HomeNeedsService: Marketplace is Online!"

if __name__ == '__main__':
    app.run(debug=True)