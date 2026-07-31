import os
import stripe
import csv
import time
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# Set your Stripe API key from the environment variable
stripe.api_key = os.getenv('STRIPE_API_KEY')

def get_first_subscription_item(subscription):
    items = subscription['items'].data
    return items[0] if items else None

def get_current_period_timestamps(subscription):
    """Stripe API >= 2025-03 moved billing periods from Subscription to SubscriptionItem."""
    first_item = get_first_subscription_item(subscription)
    period_start = getattr(first_item, 'current_period_start', None) if first_item else None
    period_end = getattr(first_item, 'current_period_end', None) if first_item else None
    period_start = period_start or getattr(subscription, 'current_period_start', None)
    period_end = period_end or getattr(subscription, 'current_period_end', None)
    return period_start, period_end

def get_billing_interval(subscription):
    first_item = get_first_subscription_item(subscription)
    if first_item and first_item.price and first_item.price.recurring:
        return first_item.price.recurring.interval, first_item.price.recurring.interval_count

    plan = getattr(subscription, 'plan', None)
    if plan:
        return plan.interval, plan.interval_count

    return 'month', 1

def get_subscription_discount(subscription):
    """Return the primary discount (Paddle supports one discount per subscription)."""
    discount = getattr(subscription, 'discount', None)
    if discount:
        return discount

    subscription_discounts = getattr(subscription, 'discounts', None) or []
    if subscription_discounts:
        return subscription_discounts[0]

    for item in subscription['items'].data:
        item_discounts = getattr(item, 'discounts', None) or []
        if item_discounts:
            return item_discounts[0]

    return None

_coupon_cache = {}

def get_discount_coupon(discount):
    """Resolve coupon from legacy and Basil API discount shapes."""
    coupon = getattr(discount, 'coupon', None)
    if coupon and not isinstance(coupon, str):
        return coupon

    source = getattr(discount, 'source', None)
    if not source or getattr(source, 'type', None) != 'coupon':
        return None

    coupon_id = source.coupon
    if not isinstance(coupon_id, str):
        return coupon_id

    if coupon_id not in _coupon_cache:
        try:
            _coupon_cache[coupon_id] = stripe.Coupon.retrieve(coupon_id)
        except stripe.error.StripeError as e:
            print(f"Error fetching coupon {coupon_id}: {e}")
            return None

    return _coupon_cache[coupon_id]

def format_timestamp(timestamp):
    if not timestamp:
        return ''
    return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%dT%H:%M:%SZ')

# Function to fetch card token with backoff logic
def fetch_card_token(customer_id):
    while True:
        try:
            payment_methods = stripe.PaymentMethod.list(customer=customer_id, type="card")
            if payment_methods.data:
                return payment_methods.data[0].id
            else:
                return ''
        except stripe.error.StripeError as e:
            if e.http_status == 429:  # Rate limit exceeded
                print(f"Rate limit exceeded while fetching payment methods for customer {customer_id}. Retrying in 2 seconds...")
                time.sleep(2)  # Wait for 2 seconds before retrying
                continue
            print(f"Error fetching payment methods for customer {customer_id}: {e}")
            return ''

# Function to fetch tax ID with backoff logic
def fetch_tax_id(customer_id):
    while True:
        try:
            tax_ids = stripe.Customer.list_tax_ids(customer_id)
            if tax_ids.data:
                return tax_ids.data[0].value
            else:
                return ''
        except stripe.error.StripeError as e:
            if e.http_status == 429:  # Rate limit exceeded
                print(f"Rate limit exceeded while fetching tax ID for customer {customer_id}. Retrying in 2 seconds...")
                time.sleep(2)  # Wait for 2 seconds before retrying
                continue
            print(f"Error fetching tax ID for customer {customer_id}: {e}")
            return ''

# Function to calculate remaining discount cycles
def calculate_remaining_discount_cycles(subscription):
    discount = get_subscription_discount(subscription)
    if not discount:
        return '', ''  # No discount applied

    coupon = get_discount_coupon(discount)
    if not coupon:
        return discount.id, ''

    discount_start = datetime.utcfromtimestamp(discount.start)
    billing_interval, billing_interval_count = get_billing_interval(subscription)

    # Check if the discount is repeating or once
    if coupon.duration == 'forever':
        return discount.id, '∞'  # No remaining cycles limit for forever discounts

    total_cycles = coupon.duration_in_months if coupon.duration == 'repeating' else 1

    # Calculate the number of billing cycles that have passed since the discount started
    current_date = datetime.utcnow()

    if billing_interval == 'month':
        cycles_used = (current_date.year - discount_start.year) * 12 + (current_date.month - discount_start.month)
    elif billing_interval == 'year':
        cycles_used = current_date.year - discount_start.year
    else:
        # Handle other intervals like 'week', etc., if applicable
        billing_days = billing_interval_count * 7 if billing_interval == 'week' else billing_interval_count
        cycles_used = (current_date - discount_start).days // billing_days

    # Calculate remaining cycles
    remaining_cycles = total_cycles - cycles_used
    if remaining_cycles < 0:
        remaining_cycles = 0  # Ensure it doesn't go negative

    return discount.id, remaining_cycles  # Return discount ID and remaining cycles

# Function to fetch subscription and customer data from Stripe
def fetch_stripe_subscriptions(limit=100):
    subscriptions_with_customers = []
    
    try:
        # Expand both 'customer' and 'items.data' in the subscription list call
        subscriptions = stripe.Subscription.list(limit=limit, expand=["data.customer", "data.items.data.price", "data.items.data.discounts"])
        
        for subscription in subscriptions.auto_paging_iter():
            # Skip subscriptions with status "past_due"
            if subscription.status == 'past_due':
                continue

            customer = subscription.customer

            # Fetch customer details
            address_country_code = customer.address.country if customer.address else ''
            address_street_line1 = customer.address.line1 if customer.address else ''
            address_street_line2 = customer.address.line2 if customer.address else ''
            address_city = customer.address.city if customer.address else ''
            address_region = customer.address.state if customer.address else ''

            period_start, period_end = get_current_period_timestamps(subscription)
            current_period_started_at = format_timestamp(period_start)
            current_period_ends_at = format_timestamp(period_end)
            started_at = format_timestamp(subscription.start_date)

            card_token = fetch_card_token(customer.id)
            business_tax_identifier = fetch_tax_id(customer.id)
            business_name = customer.name or ''

            # Collection mode and manual-specific fields
            collection_mode = 'automatic' if subscription.collection_method == 'charge_automatically' else 'manual'
            
            # Initialize manual-specific fields
            enable_checkout = ''
            purchase_order_number = ''
            additional_information = ''
            payment_terms_frequency = ''
            payment_terms_interval = ''
            
            # Check for manual collection
            if collection_mode == 'manual':
                enable_checkout = 'TRUE'
                purchase_order_number = 'No specific PO field in Stripe. Appropriate values may be found in custom_fields. Add logic to populate this column for manual subs, or delete.'
                additional_information = 'No specific additional_information field in Stripe. The description field in the Invoice API may contain appropriate values. Add logic to populate this column for manual subs, or delete.'
                
                # Fetch days_until_due from the subscription
                days_until_due = getattr(subscription, 'days_until_due', None)
                if days_until_due is not None:
                    payment_terms_frequency = str(days_until_due)
                    payment_terms_interval = 'day'

            # Trial period information
            trial_period_frequency = ''
            trial_period_interval = ''
            if subscription.trial_end:
                trial_end_date = datetime.utcfromtimestamp(subscription.trial_end)
                current_date = datetime.utcnow()
                time_left = trial_end_date - current_date
                
                if time_left.days >= 0:  # Check if there are days left
                    trial_period_frequency = str(time_left.days + 1)  # Add 1 to include the current day
                    trial_period_interval = 'day'  # Always set to "day"

            # Calculate discount ID and remaining cycles
            discount_id, remaining_cycles = calculate_remaining_discount_cycles(subscription)

            # Initialize subscription data
            subscription_data = {
                'customer_email': customer.email,
                'customer_full_name': customer.name or '',
                'customer_external_id': customer.id,
                'business_tax_identifier': business_tax_identifier,
                'business_name': business_name,
                'business_company_number': "Not found in Stripe. Add your own internal value if desired, otherwise delete this column",
                'business_external_id': "Not found in Stripe. Add your own internal value if desired, otherwise delete this column",
                'address_country_code': address_country_code,
                'address_street_line1': address_street_line1,
                'address_street_line2': address_street_line2,
                'address_city': address_city,
                'address_region': address_region,
                'address_postal_code': customer.address.postal_code if customer.address else '',
                'address_external_id': "Not found in Stripe. Add your own internal value if desired, otherwise delete this column",
                # The Stripe API automatically filters out subscriptions that are cancelled
                'status': subscription.status,
                'currency_code': subscription.currency.upper(),
                'started_at': started_at,
                'paused_at': 'Not found in the Stripe API. Enrich from your database, otherwise delete this column if not needed.',
                'collection_mode': collection_mode,
                'enable_checkout': enable_checkout,
                'purchase_order_number': purchase_order_number,
                'additional_information': additional_information,
                'payment_terms_frequency': payment_terms_frequency,
                'payment_terms_interval': payment_terms_interval,
                'current_period_started_at': current_period_started_at,
                'current_period_ends_at': current_period_ends_at,
                'trial_period_frequency': trial_period_frequency,
                'trial_period_interval': trial_period_interval,
                'subscription_external_id': subscription.id,
                'card_token': card_token,
                'discount_id': discount_id,
                'discount_remaining_cycles': remaining_cycles,
                'subscription_custom_data_key_1': 'Amend the logic to add any custom_data key here. Repeat columns as necessary for more custom_data. Delete if unnecessary.',
                'subscription_custom_data_value_1': 'Amend the logic to add any custom_data value here. Repeat columns as necessary for more custom_data. Delete if unnecessary.'
            }

            # Check if the subscription is paused
            if subscription.pause_collection:
                subscription_data['status'] = 'paused'

            # Fetch subscription items
            items = subscription['items'].data
            if items:
                for i, item in enumerate(items, start=1):
                    subscription_data[f'price_id_{i}'] = item.price.id if item.price else ''
                    subscription_data[f'quantity_{i}'] = item.quantity
            else:
                subscription_data['price_id_1'] = ''
                subscription_data['quantity_1'] = ''

            subscriptions_with_customers.append(subscription_data)
    
    except stripe.error.StripeError as e:
        print(f"Error fetching data from Stripe: {e}")
    
    return subscriptions_with_customers

# Function to export data to CSV
def export_to_csv(data, file_path='paddle_migration_output.csv'):
    headers = [
        'customer_email', 'customer_full_name', 'customer_external_id', 'business_tax_identifier',
        'business_name', 'business_company_number', 'business_external_id', 'address_country_code',
        'address_street_line1', 'address_street_line2', 'address_city', 'address_region', 'address_postal_code',
        'address_external_id', 'status', 'currency_code', 'started_at', 'paused_at', 'collection_mode', 'enable_checkout',
        'purchase_order_number', 'additional_information', 'payment_terms_frequency', 'payment_terms_interval',
        'current_period_started_at', 'current_period_ends_at', 'trial_period_frequency', 'trial_period_interval',
        'subscription_external_id', 'card_token', 'discount_id', 'discount_remaining_cycles', 'subscription_custom_data_key_1', 'subscription_custom_data_value_1'
    ]
    
    # Initialize max_items to track the maximum number of price_id fields
    max_items = 0

    # Loop through the data to find the maximum number of items in any subscription
    for subscription in data:
        item_count = sum(1 for key in subscription.keys() if key.startswith('price_id_'))
        max_items = max(max_items, item_count)

    # Add dynamic headers for price IDs and their corresponding quantities
    for i in range(1, max_items + 1):
        headers.append(f'price_id_{i}')
        headers.append(f'quantity_{i}')
    
    with open(file_path, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        for row in data:
            writer.writerow(row)

# Main function to orchestrate the script
def main():
    subscriptions_data = fetch_stripe_subscriptions(limit=100)
    export_to_csv(subscriptions_data)
    
    # Print success message
    print(f"{len(subscriptions_data)} subscriptions processed successfully. Data exported to paddle_migration_output.csv")

if __name__ == "__main__":
    main()
