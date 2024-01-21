from flask import Flask
import os

app = Flask(__name__)
config_color = os.environ.get("CONFIG_COLOR")

@app.route("/")
def hello_world():
    return f"<p>Hello, {config_color} world!</p>"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)