import csv

def load_mapping(file_path, key_column, value_column):
    mapping = {}
    with open(file_path, mode='r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        for line_number, row in enumerate(reader, start=2):
            key = (row.get(key_column) or '').strip()
            value = (row.get(value_column) or '').strip()
            # The four columns are independent lists, so rows with blanks are expected.
            # A half-filled row is a mistake worth shouting about: mapping '' would
            # rewrite every empty cell in the export with a real Paddle ID.
            if not key and not value:
                continue
            if not key or not value:
                print(f"Warning: {file_path} line {line_number} fills in only one of "
                      f"{key_column}/{value_column}. Ignoring the row.")
                continue
            mapping[key] = value
    return mapping

def map_prices(rows, price_mapping):
    # Map the prices
    mapped = 0
    unmapped = set()
    for row in rows:
        for key in row.keys():
            if not key.startswith('price_id_'):
                continue
            stripe_price_id = row[key]
            if not stripe_price_id:
                continue
            if stripe_price_id in price_mapping:
                row[key] = price_mapping[stripe_price_id]
                mapped += 1
            else:
                unmapped.add(stripe_price_id)
    return mapped, unmapped

def map_discounts(rows, discount_mapping):
    # Map the discounts
    mapped = 0
    unmapped = set()
    for row in rows:
        stripe_discount_id = row.get('discount_id')
        if not stripe_discount_id:
            continue
        if stripe_discount_id in discount_mapping:
            row['discount_id'] = discount_mapping[stripe_discount_id]
            mapped += 1
        else:
            unmapped.add(stripe_discount_id)
    return mapped, unmapped

def report(label, mapped, unmapped):
    print(f"{label} mapped successfully. {mapped} value(s) replaced.")
    if unmapped:
        # Left untouched on purpose: a Stripe ID in a Paddle column is easier to spot
        # than a silently dropped one, but it will be rejected at import.
        print(f"Warning: {len(unmapped)} Stripe ID(s) have no entry in the reference file "
              f"and were left as-is:")
        for value in sorted(unmapped):
            print(f"  {value}")

def main():
    input_file = 'paddle_migration_output.csv'
    mapping_file = 'prices-discounts-mapping-ref.csv'
    output_file = 'paddle_migration_output_mapped.csv'

    # Load the input CSV
    with open(input_file, mode='r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # Ask the user if they want to map prices
    map_prices_choice = input("Do you want to map prices? (y/n): ").strip().lower()
    if map_prices_choice == 'y':
        price_mapping = load_mapping(mapping_file, 'stripe_price_id', 'paddle_price_id')
        report("Prices", *map_prices(rows, price_mapping))

    # Ask the user if they want to map discounts
    map_discounts_choice = input("Do you want to map discounts? (y/n): ").strip().lower()
    if map_discounts_choice == 'y':
        if 'discount_id' not in (fieldnames or []):
            print(f"Skipping discounts: {input_file} has no discount_id column.")
        else:
            discount_mapping = load_mapping(mapping_file, 'stripe_discount_id', 'paddle_discount_id')
            report("Discounts", *map_discounts(rows, discount_mapping))

    # Write the output CSV
    with open(output_file, mode='w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Output saved to {output_file}")

if __name__ == "__main__":
    main()
