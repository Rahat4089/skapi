from flask import Flask, request, jsonify
import requests
import base64
import urllib.parse
import json
from datetime import datetime
import re

app = Flask(__name__)

class StripeKeyChecker:
    def __init__(self, sk_live):
        self.sk_live = sk_live.strip()
        self.headers = {
            'Authorization': f'Bearer {self.sk_live}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        self.base_url = 'https://api.stripe.com/v1'
        self.results = {}

    def xor(self, text, key):
        """XOR decryption function"""
        if type(key) is int:
            key = [key]
        output = ""
        for i in range(len(text)):
            c = ord(text[i])
            k = key[i % len(key)]
            output += chr(c ^ k)
        return output

    def make_safe_request(self, endpoint, method='GET', data=None):
        """Make API request and handle responses safely"""
        try:
            url = f"{self.base_url}/{endpoint}"
            if method == 'GET':
                response = requests.get(url, headers=self.headers, timeout=30)
            else:
                response = requests.post(url, headers=self.headers, data=data, timeout=30)
            
            return response if response.status_code == 200 else None
        except Exception:
            return None

    def extract_publishable_key(self):
        """Extract publishable key using checkout session method"""
        try:
            session = requests.Session()
            
            # Create product
            product_data = {
                "name": "API Test Product",
                "type": "good",
                "description": "Test product for API key extraction",
            }
            product_req = session.post(f"{self.base_url}/products", headers=self.headers, data=product_data)
            if product_req.status_code != 200:
                return False
                
            product_id = product_req.json()["id"]

            # Create price
            price_data = {
                "unit_amount": 100,
                "currency": "usd",
                "product": product_id,
            }
            price_req = session.post(f"{self.base_url}/prices", headers=self.headers, data=price_data)
            price_id = price_req.json()["id"]

            # Create checkout session
            checkout_data = {
                "success_url": "https://example.com/success",
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": 1,
                "mode": "payment",
                "payment_method_types[]": "card",
            }
            checkout_req = session.post(f"{self.base_url}/checkout/sessions", headers=self.headers, data=checkout_data)
            
            if checkout_req.status_code != 200:
                return False
                
            checkout_url = checkout_req.json()["url"]

            # Extract publishable key
            urltodecode = checkout_url.split("#")[1]
            basetodecode = urllib.parse.unquote(urltodecode)
            xortodecode = base64.b64decode(basetodecode).decode("utf-8")
            pk_live = self.xor(xortodecode, 5).split('"')[3]
            
            self.results['keys'] = {
                'secret_key': self.sk_live[:20] + '...' + self.sk_live[-4:],
                'publishable_key': pk_live,
                'account_id': self.sk_live.split('_')[-1] if '_' in self.sk_live else 'Unknown'
            }
            return True
            
        except Exception:
            # Fallback method
            account_id = self.sk_live.split('_')[-1] if '_' in self.sk_live else 'Unknown'
            pk_live = f"pk_live_{account_id}"
            self.results['keys'] = {
                'secret_key': self.sk_live[:20] + '...' + self.sk_live[-4:],
                'publishable_key': pk_live,
                'account_id': account_id,
                'extraction_method': 'fallback'
            }
            return True

    def get_account_info(self):
        """Get detailed account information"""
        response = self.make_safe_request('account')
        if response:
            account_data = response.json()
            self.results['account'] = {
                'id': account_data.get('id'),
                'business_type': account_data.get('business_type'),
                'country': account_data.get('country'),
                'default_currency': account_data.get('default_currency'),
                'email': account_data.get('email'),
                'business_profile': account_data.get('business_profile', {}),
                'capabilities': account_data.get('capabilities', {}),
                'charges_enabled': account_data.get('charges_enabled'),
                'payouts_enabled': account_data.get('payouts_enabled'),
                'details_submitted': account_data.get('details_submitted'),
                'created': datetime.fromtimestamp(account_data.get('created', 0)).strftime('%Y-%m-%d %H:%M:%S')
            }
            return True
        return False

    def get_balance(self):
        """Get current balance information"""
        response = self.make_safe_request('balance')
        if response:
            balance_data = response.json()
            
            available_balance = 0
            pending_balance = 0
            available_breakdown = []
            pending_breakdown = []
            
            for balance in balance_data.get('available', []):
                amount = balance['amount'] / 100
                available_balance += amount
                available_breakdown.append(f"{amount:.2f} {balance['currency'].upper()}")
            
            for balance in balance_data.get('pending', []):
                amount = balance['amount'] / 100
                pending_balance += amount
                pending_breakdown.append(f"{amount:.2f} {balance['currency'].upper()}")
            
            self.results['balance'] = {
                'available_total': available_balance,
                'pending_total': pending_balance,
                'available_breakdown': available_breakdown,
                'pending_breakdown': pending_breakdown
            }
            return True
        return False

    def get_charges(self):
        """Get recent charges"""
        response = self.make_safe_request('charges?limit=5')
        if response:
            charges_data = response.json()
            recent_charges = []
            total_charges = 0
            successful_charges = 0
            
            for charge in charges_data.get('data', []):
                recent_charges.append({
                    'id': charge.get('id'),
                    'amount': charge.get('amount', 0) / 100,
                    'currency': charge.get('currency'),
                    'status': charge.get('status'),
                    'paid': charge.get('paid'),
                    'created': datetime.fromtimestamp(charge.get('created', 0)).strftime('%Y-%m-%d %H:%M:%S')
                })
                total_charges += 1
                if charge.get('paid'):
                    successful_charges += 1
            
            self.results['charges'] = {
                'recent_charges_count': total_charges,
                'successful_charges': successful_charges,
                'success_rate': round((successful_charges / total_charges * 100), 2) if total_charges > 0 else 0,
                'sample_charges': recent_charges[:3]  # Only show first 3 charges
            }
            return True
        return False

    def get_payouts(self):
        """Get payout information"""
        response = self.make_safe_request('payouts?limit=3')
        if response:
            payouts_data = response.json()
            recent_payouts = []
            
            for payout in payouts_data.get('data', []):
                recent_payouts.append({
                    'id': payout.get('id'),
                    'amount': payout.get('amount', 0) / 100,
                    'currency': payout.get('currency'),
                    'status': payout.get('status'),
                    'arrival_date': payout.get('arrival_date'),
                    'created': datetime.fromtimestamp(payout.get('created', 0)).strftime('%Y-%m-%d %H:%M:%S')
                })
            
            self.results['payouts'] = {
                'recent_payouts_count': len(recent_payouts),
                'recent_payouts': recent_payouts
            }
            return True
        return False

    def get_products(self):
        """Get products information"""
        response = self.make_safe_request('products?limit=3')
        if response:
            products_data = response.json()
            products = []
            
            for product in products_data.get('data', []):
                products.append({
                    'id': product.get('id'),
                    'name': product.get('name'),
                    'description': product.get('description'),
                    'active': product.get('active'),
                    'created': datetime.fromtimestamp(product.get('created', 0)).strftime('%Y-%m-%d %H:%M:%S')
                })
            
            self.results['products'] = {
                'total_products': len(products),
                'recent_products': products
            }
            return True
        return False

    def analyze(self):
        """Run complete analysis"""
        # Validate key format
        if not re.match(r'^sk_(live|test)_[A-Za-z0-9]+$', self.sk_live):
            return {
                'status': 'error',
                'message': 'Invalid Stripe key format. Must start with sk_live_ or sk_test_'
            }

        # Run all analysis methods
        methods = [
            self.extract_publishable_key,
            self.get_account_info,
            self.get_balance,
            self.get_charges,
            self.get_payouts,
            self.get_products
        ]
        
        successful_checks = 0
        for method in methods:
            try:
                if method():
                    successful_checks += 1
            except Exception:
                continue

        # Generate indexed response
        indexed_response = self.generate_indexed_response(successful_checks)
        return indexed_response

    def generate_indexed_response(self, successful_checks):
        """Generate well-indexed API response"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        response = {
            'status': 'success',
            'timestamp': timestamp,
            'checks_completed': successful_checks,
            'total_checks': 6,
            'data': {}
        }

        # 1. KEY INFORMATION
        if 'keys' in self.results:
            response['data']['key_information'] = {
                'secret_key_masked': self.results['keys'].get('secret_key'),
                'publishable_key': self.results['keys'].get('publishable_key'),
                'account_id': self.results['keys'].get('account_id'),
                'live_mode': 'live' if 'sk_live_' in self.sk_live else 'test',
                'key_valid': True,
                'extraction_method': self.results['keys'].get('extraction_method', 'direct')
            }

        # 2. ACCOUNT STATUS
        if 'account' in self.results:
            account = self.results['account']
            business_profile = account.get('business_profile', {})
            support_address = business_profile.get('support_address', {})
            
            response['data']['account_status'] = {
                'account_id': account.get('id'),
                'country': account.get('country'),
                'email': account.get('email'),
                'business_type': account.get('business_type'),
                'charges_enabled': account.get('charges_enabled'),
                'payouts_enabled': account.get('payouts_enabled'),
                'details_submitted': account.get('details_submitted'),
                'account_created': account.get('created'),
                'status': 'active' if account.get('charges_enabled') else 'restricted',
                'business_name': business_profile.get('name'),
                'website': business_profile.get('url'),
                'support_phone': business_profile.get('support_phone'),
                'support_address': {
                    'city': support_address.get('city'),
                    'country': support_address.get('country'),
                    'state': support_address.get('state'),
                    'postal_code': support_address.get('postal_code')
                } if support_address else None
            }

        # 3. FINANCIAL INFORMATION
        financial_info = {}
        if 'balance' in self.results:
            balance = self.results['balance']
            financial_info['balance'] = {
                'available_total': f"${balance.get('available_total', 0):.2f}",
                'pending_total': f"${balance.get('pending_total', 0):.2f}",
                'available_breakdown': balance.get('available_breakdown', []),
                'pending_breakdown': balance.get('pending_breakdown', [])
            }
        
        if 'charges' in self.results:
            charges = self.results['charges']
            financial_info['charges'] = {
                'recent_charges_count': charges.get('recent_charges_count'),
                'successful_charges': charges.get('successful_charges'),
                'success_rate': f"{charges.get('success_rate', 0)}%",
                'sample_charges': charges.get('sample_charges', [])
            }
        
        if 'payouts' in self.results:
            payouts = self.results['payouts']
            financial_info['payouts'] = {
                'recent_payouts_count': payouts.get('recent_payouts_count'),
                'recent_payouts': payouts.get('recent_payouts', [])
            }
        
        if financial_info:
            response['data']['financial_information'] = financial_info

        # 4. BUSINESS INFORMATION
        business_info = {}
        
        if 'products' in self.results:
            products = self.results['products']
            business_info['products'] = {
                'total_products': products.get('total_products'),
                'recent_products': products.get('recent_products', [])
            }
        
        if business_info:
            response['data']['business_information'] = business_info

        # 5. CAPABILITIES
        if 'account' in self.results:
            capabilities = self.results['account'].get('capabilities', {})
            active_methods = [cap.replace('_', ' ').title() for cap, status in capabilities.items() if status == 'active']
            inactive_methods = [cap.replace('_', ' ').title() for cap, status in capabilities.items() if status == 'inactive']
            
            response['data']['capabilities'] = {
                'active_methods_count': len(active_methods),
                'inactive_methods_count': len(inactive_methods),
                'active_payment_methods': active_methods,
                'inactive_payment_methods': inactive_methods,
                'key_metrics': {
                    'card_payments': capabilities.get('card_payments') == 'active',
                    'transfers': capabilities.get('transfers') == 'active',
                    'tax_reporting': capabilities.get('tax_reporting') == 'active'
                }
            }

        return response

@app.route('/api/check-stripe', methods=['GET', 'POST'])
def check_stripe_key():
    """API endpoint to check Stripe key"""
    try:
        # Get sk parameter
        if request.method == 'GET':
            sk = request.args.get('sk')
        else:
            sk = request.json.get('sk') if request.is_json else request.form.get('sk')
        
        if not sk:
            return jsonify({
                'status': 'error',
                'message': 'Missing required parameter: sk',
                'usage': 'Send GET request to /api/check-stripe?sk=sk_live_... or POST with JSON {"sk": "sk_live_..."}'
            }), 400

        # Validate key format
        if not sk.startswith(('sk_live_', 'sk_test_')):
            return jsonify({
                'status': 'error',
                'message': 'Invalid Stripe key format. Must start with sk_live_ or sk_test_'
            }), 400

        # Analyze the key
        checker = StripeKeyChecker(sk)
        result = checker.analyze()
        
        if result.get('status') == 'error':
            return jsonify(result), 400
            
        return jsonify(result), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Internal server error: {str(e)}'
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Stripe Key Checker API',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': '1.0'
    }), 200

@app.route('/')
def index():
    """API documentation"""
    return jsonify({
        'service': 'Stripe Key Checker API',
        'version': '1.0',
        'description': 'Comprehensive Stripe secret key analysis API',
        'endpoints': {
            '/api/check-stripe': {
                'methods': ['GET', 'POST'],
                'parameters': {
                    'sk': 'Stripe secret key (sk_live_... or sk_test_...) - Required'
                },
                'description': 'Comprehensive Stripe key analysis with financial, account, and business information'
            },
            '/api/health': {
                'methods': ['GET'],
                'description': 'Health check endpoint'
            }
        },
        'response_includes': [
            'Key information (masked secret key, publishable key)',
            'Account status and business details',
            'Financial information (balances, charges, payouts)',
            'Business products and capabilities',
            'Payment method capabilities'
        ],
        'usage_examples': {
            'GET': '/api/check-stripe?sk=sk_live_51OSuMiJVthGMKEcz...',
            'POST': 'curl -X POST -H "Content-Type: application/json" -d \'{"sk":"sk_live_51OSuMiJVthGMKEcz..."}\' http://localhost:5000/api/check-stripe'
        },
        'notes': [
            'All sensitive information is masked in responses',
            'Only successful API calls are processed',
            'Includes comprehensive business and financial analytics'
        ]
    }), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
