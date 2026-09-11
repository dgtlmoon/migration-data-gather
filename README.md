# Stripe > Paddle Migration Data Gathering Scripts

This collection of scripts  is designed to gather subscription and customer data from Stripe, map prices and discounts to their Paddle equivalents, and export the data to Paddle-compatible CSV files for migration purposes.

## Files

1. **stripe-mig-data-gather.py**
2. **prices-discounts-mapping-ref.csv**
3. **prices-discounts-mapping.py**

## How The 3 Files Work Together

1. **stripe-mig-data-gather.py**: Script that fetches subscription and customer data from Stripe and exports it to `paddle_migration_output.csv`.
2. **prices-discounts-mapping-ref.csv**: Template that provides the reference mapping for price and discount IDs used by `prices-discounts-mapping.py`.
3. **prices-discounts-mapping.py**: Uses the output of `stripe-mig-data-gather.py` (`paddle_migration_output.csv`) and `prices-discounts-mapping-ref.csv` to map Stripe price and discount IDs to Paddle IDs, and exports the mapped data to `paddle_migration_output_mapped.csv`.

## Prerequisites

- Python 3.x
- Stripe API key — see [Stripe API Key Permissions](#stripe-api-key-permissions) below for which permissions to grant
- `.env` file with the Stripe API key:
  ```
  STRIPE_API_KEY=your_stripe_api_key
  ```

## Stripe API Key Permissions

### Use a dedicated key for the migration

Don't reuse an existing application/secret key for this. Create a **restricted API key** (starts with `rk_live_`) in the Stripe Dashboard under [Developers > API keys](https://dashboard.stripe.com/apikeys) > **Create restricted key**, named something obvious like `paddle-migration-export`, and give it **only the read permissions listed below**. A dedicated key means:

- The key can only read data — it can never create charges, refunds, or modify your subscribers, even if it leaks.
- You can see exactly which API calls this migration made via **⋯ > View request logs** on that key.
- You can **expire the key** the moment the migration data has been handed over, without affecting anything else you run.

Start from "no permissions" rather than a preset, set everything to **None**, then switch on only the resources below. **Write access is not needed anywhere** — both scripts are read-only against Stripe.

Optionally, attach an [access policy](https://dashboard.stripe.com/api-access-policies) to the key restricting it to the IP address you run the export from.

### Permissions to enable (all **Read**)

| Permission (Dashboard resource) | Level | Why it's needed |
| --- | --- | --- |
| **Subscriptions** | Read | `GET /v1/subscriptions` — the main listing that drives the whole export. |
| **Customers** | Read | Customer is expanded on each subscription (email, name, address), and `GET /v1/customers/{id}/tax_ids` provides `business_tax_identifier`. |
| **Prices** | Read | Subscription items expand `price`, used for `price_id_N` and the billing interval. |
| **Payment Methods** | Read | `GET /v1/payment_methods?customer=...&type=card` provides the `card_token` column. |
| **Coupons** | Read | `GET /v1/coupons/{id}` resolves coupon duration for `discount_remaining_cycles`. |

Notes:

- Permission names and groupings differ slightly between Dashboard versions (for example, **Prices** may sit under the Billing group, **Payment Methods** under Core). If a call fails, Stripe returns a `403` whose error message names the exact permission to add — and you can check the key's request logs to see which endpoint was rejected.
- Customer tax IDs are covered by **Customers: Read**. If your Dashboard exposes a separate **Tax IDs** resource, enable that as Read too.
- `prices-discounts-mapping.py` does not talk to Stripe at all — it only reads the CSV files — so it needs no key.

### Live mode vs sandbox

The data you migrate is live data, so the key must be a **live mode** key. If you want to dry-run the scripts first, create the equivalent restricted key in a sandbox and run against that before switching.

### After the migration

1. Expire or rotate the key (**⋯ > Expire key** on the API keys page).
2. Delete the local `.env` file, and make sure `.env` was never committed — add it to `.gitignore` before your first run.
3. The generated CSVs contain customer PII (emails, names, addresses, tax IDs). Keep them out of version control and share them only with your Paddle Solutions Engineer.

## Installation

1. Clone the repository.
2. Install the required packages:
   ```sh
   pip3 install stripe python-dotenv
   ```

## Explanations of Each Script/File

### stripe-mig-data-gather.py

This script fetches subscription and customer data from the Stripe API and exports it to a CSV file.

#### Key Functions:
- `fetch_stripe_subscriptions(limit)`: Fetches subscription and customer data from Stripe.
- `fetch_card_token(customer_id)`: Fetches the card token for a given customer.
- `fetch_tax_id(customer_id)`: Fetches the tax ID for a given customer.
- `calculate_remaining_discount_cycles(subscription)`: Calculates the remaining discount cycles for a subscription.
- `export_to_csv(data, file_path)`: Exports the fetched data to a CSV file.
- `main()`: Orchestrates the script execution.

#### Usage:
1. Ensure you have a `.env` file with your Stripe API key in the project folder. The `.env` file should contain a declaration as follows: `STRIPE_API_KEY='Your_Stripe_API_KEY'`

2. Run the script:
   ```sh
   python3 stripe-mig-data-gather.py
   ```
3. The script will generate a CSV file named `paddle_migration_output.csv` with the fetched data.

#### Past due subscriptions:
Subscriptions in Stripe's `past_due` status are **left out of the export**, and the script now lists their IDs at the end of the run so you know who was excluded.

Paddle does not support migrating `past_due` subscriptions from an external provider. From a Paddle Solutions Engineer, when asked about this directly:

> We can't migrate past_due subs - the doc you're looking at is based on Paddle Classic to Paddle Billing migration, which is very different from third party MoRs or PSPs migrating into Paddle. We don't support migrating past_due as standard from external providers.

The document referred to is the [Paddle Classic to Paddle Billing porting guide](https://developer.paddle.com/migrate/paddle-classic/port-subscriptions), which states that *"You can migrate active, paused, as well as past due subscriptions"*. That applies to Classic-to-Billing only. It does **not** apply to a Stripe (or other third-party PSP/MoR) migration, so don't rely on it when planning this export.

Wait for dunning to finish on those subscriptions, then follow up with a separate migration for the ones that become active again. The list printed at the end of the run is what you need for that follow-up.

#### Note:
The script will return a number of columns where the data requested by Paddle is not readily available in the Stripe API. In these cases, explanatory values are provided in each column in the outputted CSV. Follow the instructions in the columns to obtain the necessary values from other sources and/or delete these columns as appropriate.

#### Example:
For example, Stripe does not provide a value for `business_company_number`, so the script will output in the respective column:
```
business_company_number: "Not found in Stripe. Add your own internal value if desired, otherwise delete this column"
```
You should either replace this with your internal value or delete the column if it is not needed. Review and action all similar columns before submitting the migration data to Paddle.

### prices-discounts-mapping-ref.csv

This 4-column CSV file should be filled out by the seller to contain the reference mapping between Stripe and Paddle price and discount IDs. Below are the required columns. You can edit the example provided with your own Stripe and Paddle ID's.

#### Columns:
- `stripe_price_id`: Stripe price ID.
- `paddle_price_id`: Equivalent Paddle price ID.
- `stripe_discount_id`: Stripe discount ID.
- `paddle_discount_id`: Equivalent Paddle discount ID.

### prices-discounts-mapping.py

This script maps Stripe price and discount IDs to Paddle price and discount IDs using a reference CSV file.

#### Key Functions:
- `load_mapping(file_path, key_column, value_column)`: Loads the mapping from a CSV file.
- `map_prices(rows, price_mapping)`: Maps Stripe price IDs to Paddle price IDs.
- `map_discounts(rows, discount_mapping)`: Maps Stripe discount IDs to Paddle discount IDs.
- `main()`: Orchestrates the script execution.

#### Usage:
1. Ensure you have the following files:
   - `paddle_migration_output.csv` generated by `stripe-mig-data-gather.py`.
   - `prices-discounts-mapping-ref.csv` containing the reference mapping between Stripe and Paddle price and discount IDs. You need to create this for yourself. You can edit the example provided with your own ID's.
2. Run the script:
   ```sh
   python3 prices-discounts-mapping.py
   ```
3. You will be asked if you want to map prices, followed by discounts. This gives you the option to use the script to map e.g. only discounts, if you had previously mapped only prices. 
4. The script will generate a CSV file named `paddle_migration_output_mapped.csv` with the mapped data.

## After Running Both Scripts Successfully

1. Review the data and action any columns where data is missing or can be deleted (guidance will be provided within the column values in the outputted CSVs)
2. Sense check and compare the data generated by the script against your subscriber base to ensure values are exported as expected. Paddle will import the data as provided by you and accepts no responsibility for innaccuracies that are introduced during the Stripe data export. 
3. Share the checked file `paddle_migration_output_mapped.csv` with your Solutions Engineer who will advise on next steps.

## Important Caveats to Note

- Stripe does not surface `paused_at` values in its API. You may need to pull this from your database, if available.
- `enable_checkout` column in the Paddle migration CSV - if the subscription is manual, this defaults to `TRUE`, meaning a checkout will be available on the subscriber’s invoices. If you do not want this to be the case, amend the script to populate ‘FALSE’ instead.
- `purchase_order_number` column in the Paddle migration CSV - there is no specific field for this in Stripe. You may be storing this as custom data. You should update the script to pull the desired value here.
- `additional_information` column in the Paddle migration CSV - the corresponding value may be found the “description” value in the Stripe Invoice API. Check and include if necessary.
- `payment_terms_interval` column in the Paddle migration - the Stripe API appears to assume “day” in every case. “day” is automatically used here. Update this if you have terms not measured in days.
- The script pulls in Stripe discount IDs. You’ll need to map these against the equivalent discount_id’s you have created in Paddle before sharing the file for import. You should also check that the `discount_remaining_cycles` match your expectation.
- Paddle only supports one `discount_id` per subscription. In Stripe, you may have multiple discounts applied to a subscription. The price and discount mapping script only attempts to map a single Paddle discount_id that you provide against a single Stripe discount_id. You will need to ensure you are pulling the correct discount, or else applying a larger discount in Paddle that accounts for the total Stripe discount amount. 
- This script is provided as a reference to help sellers in gathering the data needed for migration from the Stripe API, but is not a definitive method for pulling this data. All columns in the final CSV for migration should be carefully checked to ensure accuracy with your existing subscriber base. Data may need to be enriched from other sources or otherwise manipulated if the information or format is not correct. Responsibility for verifying the data sits with the seller and Paddle is not responsible for data innaccuracies introduced during the export process from Stripe or any legacy subscription management system. 
