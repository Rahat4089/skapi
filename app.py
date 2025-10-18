from flask import Flask, request, jsonify, render_template
import requests
import base64
import urllib.parse
import re
import json
from datetime import datetime
import concurrent.futures
import threading
from queue import Queue
import time

app = Flask(__name__)

# In-memory storage for results
results_store = {}
lock = threading.Lock()

def xor(text, key):
    if type(key) is int:
        key = [key]
    output = ""
    for i in range(len(text)):
        c = ord(text[i])
        k = key[i % len(key)]
        output += chr(c ^ k)
    return output

def decode_checkout_url(checkout_url):
    try:
        encoded_part = checkout_url.split("#")[1]
        url_decoded = urllib.parse.unquote(encoded_part)
        base64_decoded = base64.b64decode(url_decoded).decode('latin-1')
        
        found_pk = None
        for xor_key in [5, 3, 4, 6, 7]:
            xored = xor(base64_decoded, xor_key)
            pk_pattern = r'pk_(test|live)_[A-Za-z0-9_]+'
            match = re.search(pk_pattern, xored)
            if match:
                found_pk = match.group()
                break
        
        if not found_pk:
            pk_pattern = r'pk_(test|live)_[A-Za-z0-9_]+'
            match = re.search(pk_pattern, base64_decoded)
            if match:
                found_pk = match.group()
        
        return found_pk
    except:
        return None

def test_cc_payment_integration(sk_key):
    session = requests.Session()
    headers = {"Authorization": f"Bearer {sk_key}"}
    
    try:
        payment_data = {
            "amount": 100,
            "currency": "usd",
            "payment_method_types[]": "card",
            "payment_method_data[type]": "card",
            "payment_method_data[card][number]": "4242424242424242",
            "payment_method_data[card][exp_month]": "12",
            "payment_method_data[card][exp_year]": "2030",
            "payment_method_data[card][cvc]": "123",
            "confirm": "true",
            "return_url": "https://example.com/return"
        }
        
        response = session.post("https://api.stripe.com/v1/payment_intents", 
                              headers=headers, data=payment_data, timeout=10)
        
        return response.status_code == 200
    except:
        return False

def get_basic_account_info(sk_key):
    """Get basic account info quickly for mass checking"""
    session = requests.Session()
    headers = {"Authorization": f"Bearer {sk_key}"}
    
    result = {
        "status": "unknown",
        "sk_key": sk_key,
        "pk_key": "Unknown",
        "charge_mode": "Unknown",
        "currency": "Unknown",
        "balance": 0,
        "pending_balance": 0,
        "url": "Unknown",
        "account_name": "Unknown",
        "error": None,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        # Test if key is valid
        account_req = session.get("https://api.stripe.com/v1/account", 
                                headers=headers, timeout=10)
        
        if account_req.status_code == 200:
            account_data = account_req.json()
            result["charge_mode"] = "Live" if account_data.get("livemode") else "Test"
            result["currency"] = account_data.get("default_currency", "usd").upper()
            
            # Get business info
            business_profile = account_data.get("business_profile", {})
            result["url"] = business_profile.get("url", "Unknown")
            result["account_name"] = business_profile.get("name", "Unknown")
            
            # Get balance
            balance_req = session.get("https://api.stripe.com/v1/balance", 
                                    headers=headers, timeout=10)
            if balance_req.status_code == 200:
                balance_data = balance_req.json()
                pending_balance = sum(item.get("amount", 0) for item in balance_data.get("pending", []))
                available_balance = sum(item.get("amount", 0) for item in balance_data.get("available", []))
                result["balance"] = available_balance
                result["pending_balance"] = pending_balance
            
            # Try to extract PK key quickly
            try:
                product_req = session.post("https://api.stripe.com/v1/products", 
                                         headers=headers, 
                                         data={"name": "Test", "type": "service"}, 
                                         timeout=5)
                if product_req.status_code == 200:
                    price_req = session.post("https://api.stripe.com/v1/prices", 
                                           headers=headers,
                                           data={"unit_amount": 100, "currency": "usd", 
                                                 "product": product_req.json().get("id")},
                                           timeout=5)
                    if price_req.status_code == 200:
                        checkout_req = session.post("https://api.stripe.com/v1/checkout/sessions",
                                                  headers=headers,
                                                  data={"success_url": "https://example.com",
                                                        "line_items[0][price]": price_req.json().get("id"),
                                                        "line_items[0][quantity]": 1,
                                                        "mode": "payment"},
                                                  timeout=5)
                        if checkout_req.status_code == 200:
                            checkout_url = checkout_req.json().get("url", "")
                            pk_key = decode_checkout_url(checkout_url)
                            if pk_key:
                                result["pk_key"] = pk_key
            except:
                pass  # PK extraction is optional
            
            # Test integration status
            integration_active = test_cc_payment_integration(sk_key)
            if integration_active:
                result["status"] = "Live [Integration On]"
            else:
                result["status"] = "Live [Integration Off]"
                
        elif account_req.status_code == 401:
            result["status"] = "Invalid"
            result["error"] = "Invalid API Key"
        elif account_req.status_code == 429:
            result["status"] = "Rate Limited"
            result["error"] = "Rate limit exceeded"
        else:
            result["status"] = "Invalid"
            result["error"] = f"API Error: {account_req.status_code}"
            
    except requests.exceptions.Timeout:
        result["status"] = "Rate Limited"
        result["error"] = "Request timeout"
    except requests.exceptions.ConnectionError:
        result["status"] = "Invalid"
        result["error"] = "Connection error"
    except Exception as e:
        result["status"] = "Invalid"
        result["error"] = str(e)
    
    return result

def process_sk_keys(sk_keys, job_id):
    """Process multiple SK keys in parallel"""
    total = len(sk_keys)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_sk = {executor.submit(get_basic_account_info, sk): sk for sk in sk_keys}
        
        for i, future in enumerate(concurrent.futures.as_completed(future_to_sk)):
            sk = future_to_sk[future]
            try:
                result = future.result()
                with lock:
                    if job_id not in results_store:
                        results_store[job_id] = {"results": [], "completed": 0, "total": total}
                    results_store[job_id]["results"].append(result)
                    results_store[job_id]["completed"] = i + 1
            except Exception as e:
                error_result = {
                    "status": "Invalid",
                    "sk_key": sk,
                    "pk_key": "Unknown",
                    "charge_mode": "Unknown",
                    "currency": "Unknown",
                    "balance": 0,
                    "pending_balance": 0,
                    "url": "Unknown",
                    "account_name": "Unknown",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }
                with lock:
                    if job_id not in results_store:
                        results_store[job_id] = {"results": [], "completed": 0, "total": total}
                    results_store[job_id]["results"].append(error_result)
                    results_store[job_id]["completed"] = i + 1

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/check-single', methods=['POST'])
def check_single():
    """Check a single SK key"""
    data = request.json
    if not data or 'sk' not in data:
        return jsonify({"error": "Missing SK key"}), 400
    
    sk_key = data['sk'].strip()
    result = get_basic_account_info(sk_key)
    return jsonify(result)

@app.route('/api/check-bulk', methods=['POST'])
def check_bulk():
    """Check multiple SK keys"""
    data = request.json
    if not data or 'sks' not in data:
        return jsonify({"error": "Missing SK keys"}), 400
    
    sk_keys = [sk.strip() for sk in data['sks'] if sk.strip()]
    if not sk_keys:
        return jsonify({"error": "No valid SK keys provided"}), 400
    
    # Generate job ID
    job_id = str(int(time.time()))
    
    # Start processing in background
    threading.Thread(target=process_sk_keys, args=(sk_keys, job_id)).start()
    
    return jsonify({
        "job_id": job_id,
        "total": len(sk_keys),
        "message": "Processing started"
    })

@app.route('/api/check-progress/<job_id>')
def check_progress(job_id):
    """Check progress of bulk job"""
    if job_id not in results_store:
        return jsonify({"error": "Job not found"}), 404
    
    job_data = results_store[job_id]
    return jsonify({
        "completed": job_data["completed"],
        "total": job_data["total"],
        "progress": (job_data["completed"] / job_data["total"]) * 100,
        "results": job_data["results"]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
