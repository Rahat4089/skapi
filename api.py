from flask import Flask, request, jsonify
import requests
import base64
import urllib.parse
import asyncio
import re
import json
from datetime import datetime
from colorama import init, Fore, Back, Style
import concurrent.futures

# Initialize colorama
init(autoreset=True)

app = Flask(__name__)

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
    """Decode Stripe checkout URL to extract PK key"""
    try:
        # Extract the encoded part after #
        encoded_part = checkout_url.split("#")[1]
        
        # URL decode
        url_decoded = urllib.parse.unquote(encoded_part)
        
        # Base64 decode
        base64_decoded = base64.b64decode(url_decoded).decode('latin-1')
        
        # Try different XOR keys
        found_pk = None
        for xor_key in [5, 3, 4, 6, 7]:
            xored = xor(base64_decoded, xor_key)
            
            # Look for PK key pattern
            pk_pattern = r'pk_(test|live)_[A-Za-z0-9_]+'
            match = re.search(pk_pattern, xored)
            if match:
                found_pk = match.group()
                break
        
        if not found_pk:
            # If XOR doesn't work, try direct extraction
            pk_pattern = r'pk_(test|live)_[A-Za-z0-9_]+'
            match = re.search(pk_pattern, base64_decoded)
            if match:
                found_pk = match.group()
        
        return found_pk
        
    except Exception as e:
        return None

def format_currency(amount, currency="usd"):
    """Format currency amount properly"""
    if currency.lower() == "usd":
        return f"${amount/100:.2f}"
    elif currency.lower() == "eur":
        return f"€{amount/100:.2f}"
    elif currency.lower() == "gbp":
        return f"£{amount/100:.2f}"
    else:
        return f"{amount/100:.2f} {currency.upper()}"

def test_cc_payment_integration(sk_key):
    """Test if CC payments can be processed directly"""
    session = requests.Session()
    headers = {"Authorization": f"Bearer {sk_key}"}
    
    integration_status = {
        "cc_payments_active": False,
        "error_message": None,
        "test_result": "FAILED",
        "payment_intent_status": None,
        "requires_action": False
    }
    
    try:
        # Create a payment intent with test credit card
        payment_intent_url = "https://api.stripe.com/v1/payment_intents"
        
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
        
        response = session.post(payment_intent_url, headers=headers, data=payment_data)
        
        if response.status_code == 200:
            response_data = response.json()
            integration_status['payment_intent_status'] = response_data.get('status')
            
            if response_data.get('status') in ['succeeded', 'requires_action', 'processing']:
                integration_status['cc_payments_active'] = True
                integration_status['test_result'] = "SUCCESS"
                integration_status['requires_action'] = response_data.get('status') == 'requires_action'
        else:
            error_msg = response.json().get('error', {}).get('message', 'Unknown error')
            integration_status['error_message'] = error_msg
            
    except Exception as e:
        integration_status['error_message'] = str(e)
    
    return integration_status

def get_stripe_account_info(sk_key):
    """Get comprehensive Stripe account information"""
    session = requests.Session()
    headers = {"Authorization": f"Bearer {sk_key}"}
    
    account_info = {
        "account_id": "Unknown",
        "integration_status": "Unknown",
        "livemode": False,
        "charge_mode": "Unknown",
        "currency": "Unknown",
        "balance": {"available": 0, "pending": 0},
        "country": "Unknown",
        "site_url": "Unknown",
        "phone": "Unknown",
        "pk_key": "Unknown",
        "account_name": "Unknown",
        "email": "Unknown",
        "timezone": "Unknown",
        "default_currency": "Unknown",
        "business_type": "Unknown",
        "created": "Unknown",
        "charges_enabled": False,
        "payouts_enabled": False,
        "details_submitted": False,
        "capabilities": {},
        "statement_descriptor": "Unknown",
        "display_name": "Unknown",
        "mcc": "Unknown",
        "individual_name": "Unknown",
        "statement_prefix": "Unknown",
        "payout_schedule": "Unknown",
        "account_health": "Unknown",
        "security_restrictions": [],
        "raw_responses": {}
    }
    
    try:
        # Get account information
        account_url = "https://api.stripe.com/v1/account"
        req = session.get(account_url, headers=headers)
        
        account_info['raw_responses']['account'] = {
            'status_code': req.status_code,
            'body': req.json() if req.status_code == 200 else req.text
        }
        
        if req.status_code == 200:
            account_data = req.json()
            
            # Extract account details
            account_info["account_id"] = account_data.get("id", "Unknown")
            account_info["livemode"] = account_data.get("livemode", False)
            account_info["country"] = account_data.get("country", "Unknown").upper()
            account_info["email"] = account_data.get("email", "Unknown")
            account_info["business_type"] = account_data.get("business_type", "Unknown")
            account_info["default_currency"] = account_data.get("default_currency", "usd").upper()
            account_info["charges_enabled"] = account_data.get("charges_enabled", False)
            account_info["payouts_enabled"] = account_data.get("payouts_enabled", False)
            account_info["details_submitted"] = account_data.get("details_submitted", False)
            account_info["capabilities"] = account_data.get("capabilities", {})
            
            # Business info
            business_profile = account_data.get("business_profile", {})
            account_info["site_url"] = business_profile.get("url", "Unknown")
            account_info["account_name"] = business_profile.get("name", "Unknown")
            account_info["mcc"] = business_profile.get("mcc", "Unknown")
            account_info["phone"] = business_profile.get("support_phone", "Unknown")
            
            # Individual info
            individual = account_data.get("individual", {})
            first_name = individual.get("first_name", "")
            last_name = individual.get("last_name", "")
            account_info["individual_name"] = f"{first_name} {last_name}".strip()
            
            # Settings
            settings = account_data.get("settings", {})
            dashboard = settings.get("dashboard", {})
            account_info["display_name"] = dashboard.get("display_name", "Unknown")
            account_info["timezone"] = dashboard.get("timezone", "Unknown")
            
            # Payment settings
            payments = settings.get("payments", {})
            account_info["statement_descriptor"] = payments.get("statement_descriptor", "Unknown")
            
            # Card settings
            card_payments = settings.get("card_payments", {})
            account_info["statement_prefix"] = card_payments.get("statement_descriptor_prefix", "Unknown")
            
            # Payout settings
            payouts = settings.get("payouts", {})
            schedule = payouts.get("schedule", {})
            delay_days = schedule.get("delay_days", "Unknown")
            interval = schedule.get("interval", "Unknown")
            account_info["payout_schedule"] = f"{delay_days} days delay, {interval}"
            
            # Dates
            created_timestamp = account_data.get("created")
            if created_timestamp:
                account_info["created"] = datetime.fromtimestamp(created_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                
    except Exception as e:
        account_info["error"] = f"Account info error: {str(e)}"
    
    try:
        # Get balance information
        balance_url = "https://api.stripe.com/v1/balance"
        req = session.get(balance_url, headers=headers)
        
        account_info['raw_responses']['balance'] = {
            'status_code': req.status_code,
            'body': req.json() if req.status_code == 200 else req.text
        }
        
        if req.status_code == 200:
            balance_data = req.json()
            
            available_balance = 0
            pending_balance = 0
            
            for balance in balance_data.get("available", []):
                available_balance += balance.get("amount", 0)
                
            for balance in balance_data.get("pending", []):
                pending_balance += balance.get("amount", 0)
            
            account_info["balance"]["available"] = available_balance
            account_info["balance"]["pending"] = pending_balance
            account_info["currency"] = balance_data.get("available", [{}])[0].get("currency", "usd") if balance_data.get("available") else "usd"
            
    except Exception as e:
        if "error" not in account_info:
            account_info["error"] = f"Balance info error: {str(e)}"
        else:
            account_info["error"] += f" | Balance info error: {str(e)}"
    
    # Determine charge mode
    if "test" in sk_key:
        account_info["charge_mode"] = "Test Mode"
    else:
        account_info["charge_mode"] = "Live Mode"
    
    return account_info

def extract_pk_key(sk_key):
    """Extract PK key through checkout session"""
    session = requests.Session()
    headers = {"Authorization": f"Bearer {sk_key}"}
    
    try:
        # Create a simple product and price first
        products_url = "https://api.stripe.com/v1/products"
        prices_url = "https://api.stripe.com/v1/prices"
        checkout_sessions_url = "https://api.stripe.com/v1/checkout/sessions"
        
        # Create product
        product_data = {"name": "Test Product", "type": "service"}
        product_req = session.post(products_url, headers=headers, data=product_data)
        product_id = product_req.json().get("id") if product_req.status_code == 200 else None
        
        # Create price
        price_data = {"unit_amount": 100, "currency": "usd", "product": product_id}
        price_req = session.post(prices_url, headers=headers, data=price_data)
        price_id = price_req.json().get("id") if price_req.status_code == 200 else None
        
        # Create checkout session
        checkout_data = {
            "success_url": "https://example.com/success",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": 1,
            "mode": "payment",
        }
        checkout_req = session.post(checkout_sessions_url, headers=headers, data=checkout_data)
        
        if checkout_req.status_code == 200:
            checkout_url = checkout_req.json().get("url", "")
            pk_key = decode_checkout_url(checkout_url)
            return pk_key if pk_key else "Extraction Failed"
        else:
            return "Extraction Failed"
            
    except Exception as e:
        return f"Extraction Error: {str(e)}"

def analyze_account_health(account_info, cc_test_result):
    """Analyze account health and security status"""
    health_indicators = []
    security_restrictions = []
    
    # Health indicators
    if account_info.get("charges_enabled"):
        health_indicators.append("Charges enabled")
    else:
        health_indicators.append("Charges disabled")
    
    if account_info.get("payouts_enabled"):
        health_indicators.append("Payouts enabled")
    else:
        health_indicators.append("Payouts disabled")
    
    if account_info.get("details_submitted"):
        health_indicators.append("Details submitted")
    else:
        health_indicators.append("Details not submitted")
    
    # Security restrictions
    if not cc_test_result.get("cc_payments_active"):
        security_restrictions.append("Raw card data processing disabled")
        security_restrictions.append("Requires Stripe.js/Elements")
    
    # Determine overall health
    positive_indicators = sum(1 for indicator in health_indicators if "enabled" in indicator or "submitted" in indicator)
    
    if positive_indicators >= 2:
        account_health = "HEALTHY"
    elif positive_indicators == 1:
        account_health = "LIMITED"
    else:
        account_health = "RESTRICTED"
    
    return {
        "account_health": account_health,
        "health_indicators": health_indicators,
        "security_restrictions": security_restrictions
    }

@app.route('/api/stripe/check', methods=['GET', 'POST'])
def stripe_account_check():
    """Main endpoint to check Stripe account information"""
    if request.method == 'GET':
        sk_key = request.args.get('sk')
    else:
        sk_key = request.json.get('sk') if request.json else None
    
    if not sk_key:
        return jsonify({
            "status": "error",
            "message": "Missing 'sk' parameter. Provide Stripe secret key as 'sk' parameter."
        }), 400
    
    # Validate SK format
    if not sk_key.startswith(('sk_live_', 'sk_test_')):
        return jsonify({
            "status": "error",
            "message": "Invalid Stripe secret key format. Must start with 'sk_live_' or 'sk_test_'"
        }), 400
    
    try:
        # Run all checks in parallel for better performance
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Submit tasks
            account_future = executor.submit(get_stripe_account_info, sk_key)
            pk_future = executor.submit(extract_pk_key, sk_key)
            cc_test_future = executor.submit(test_cc_payment_integration, sk_key)
            
            # Get results
            account_info = account_future.result()
            pk_key = pk_future.result()
            cc_test_result = cc_test_future.result()
        
        # Update account info with PK key
        account_info["pk_key"] = pk_key
        
        # Analyze account health
        health_analysis = analyze_account_health(account_info, cc_test_result)
        account_info.update(health_analysis)
        
        # Add CC integration test result
        account_info["cc_integration_test"] = cc_test_result
        
        # Determine integration status
        if cc_test_result.get("cc_payments_active"):
            account_info["integration_status"] = "ACTIVE"
        else:
            account_info["integration_status"] = "OFF"
        
        # Format the response in indexed way
        response_data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "sk_key_preview": f"{sk_key[:20]}...{sk_key[-20:]}",
            "account_overview": {
                "account_id": account_info["account_id"],
                "account_name": account_info["account_name"],
                "email": account_info["email"],
                "country": account_info["country"],
                "livemode": account_info["livemode"],
                "charge_mode": account_info["charge_mode"],
                "account_health": account_info["account_health"]
            },
            "financial_information": {
                "balance_available": account_info["balance"]["available"],
                "balance_pending": account_info["balance"]["pending"],
                "currency": account_info["currency"],
                "formatted_available": format_currency(account_info["balance"]["available"], account_info["currency"]),
                "formatted_pending": format_currency(account_info["balance"]["pending"], account_info["currency"]),
                "default_currency": account_info["default_currency"],
                "payouts_enabled": account_info["payouts_enabled"],
                "charges_enabled": account_info["charges_enabled"]
            },
            "business_details": {
                "business_type": account_info["business_type"],
                "display_name": account_info["display_name"],
                "site_url": account_info["site_url"],
                "phone": account_info["phone"],
                "mcc_code": account_info["mcc"],
                "statement_descriptor": account_info["statement_descriptor"],
                "statement_prefix": account_info["statement_prefix"]
            },
            "integration_status": {
                "overall_status": account_info["integration_status"],
                "cc_payments_active": cc_test_result["cc_payments_active"],
                "raw_card_data_allowed": cc_test_result["cc_payments_active"],
                "requires_stripe_js": not cc_test_result["cc_payments_active"],
                "test_result": cc_test_result["test_result"],
                "error_message": cc_test_result["error_message"]
            },
            "capabilities": {
                "all_capabilities": account_info["capabilities"],
                "active_capabilities": [cap for cap, status in account_info["capabilities"].items() if status == "active"],
                "pending_capabilities": [cap for cap, status in account_info["capabilities"].items() if status == "pending"],
                "inactive_capabilities": [cap for cap, status in account_info["capabilities"].items() if status == "inactive"]
            },
            "security_settings": {
                "details_submitted": account_info["details_submitted"],
                "security_restrictions": account_info["security_restrictions"],
                "health_indicators": account_info["health_indicators"],
                "payout_schedule": account_info["payout_schedule"]
            },
            "keys": {
                "secret_key_preview": f"{sk_key[:20]}...{sk_key[-20:]}",
                "publishable_key": account_info["pk_key"],
                "key_type": "Live" if "pk_live" in account_info["pk_key"] else "Test"
            },
            "additional_info": {
                "timezone": account_info["timezone"],
                "individual_name": account_info["individual_name"],
                "account_created": account_info["created"]
            },
            "raw_data_summary": {
                "account_api_status": account_info["raw_responses"].get("account", {}).get("status_code", "Unknown"),
                "balance_api_status": account_info["raw_responses"].get("balance", {}).get("status_code", "Unknown"),
                "has_errors": "error" in account_info
            }
        }
        
        # Add error if present
        if "error" in account_info:
            response_data["errors"] = [account_info["error"]]
        
        return jsonify(response_data)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Internal server error: {str(e)}"
        }), 500

@app.route('/api/stripe/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "Stripe Account Information API",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/')
def index():
    """API documentation"""
    return jsonify({
        "message": "Stripe Key Information API",
        "endpoints": {
            "/api/stripe/check": "Check Stripe account information (GET/POST with 'sk' parameter)",
            "/api/stripe/health": "Health check endpoint"
        },
        "usage": {
            "GET": "/api/stripe/check?sk=sk_live_your_secret_key_here",
            "POST": "/api/stripe/check with JSON body: {'sk': 'sk_live_your_secret_key_here'}"
        },
        "example_response": {
            "status": "success",
            "account_overview": {
                "account_id": "acct_123...",
                "account_name": "Example Business",
                "livemode": True,
                "account_health": "HEALTHY"
            },
            "financial_information": {
                "balance_available": 0,
                "balance_pending": 10000,
                "formatted_available": "$0.00",
                "formatted_pending": "$100.00"
            }
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
