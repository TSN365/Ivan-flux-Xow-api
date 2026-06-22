import requests
import json
import base64
import os
import datetime
import binascii
from collections import OrderedDict
from Crypto.Cipher import AES

# 🔐 GitHub Secrets
AES_SECRET = os.getenv("AES_SECRET")
TARGET_URL = os.getenv("LIVXOW_URL")

def get_token():
    """Generates a security token based on current UTC time."""
    current_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        encoded_bytes = base64.b64encode(current_time.encode('utf-8'))
        encoded_str = encoded_bytes.decode('utf-8')
        reversed_b64 = encoded_str[::-1]
        hex_str = binascii.hexlify(reversed_b64.encode('utf-8')).decode('utf-8')
        return hex_str[::-1]
    except: return None

def format_match_date(date_str):
    """Reformats date string to YYYY/MM/DD."""
    try:
        if "/" in date_str:
            parts = date_str.split("/")
            if len(parts) == 3: return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except: pass
    return date_str

def process_links(links_input):
    """Applies branding, clean tokenApi, and standardizes link keys."""
    final_list = []
    if isinstance(links_input, str):
        try: links_input = json.loads(links_input)
        except: return []
    if not isinstance(links_input, list): return []

    for link_obj in links_input:
        original_name = link_obj.get("name", "").strip()
        link_val = link_obj.get("link", "") or link_obj.get("url", "")
        stream_type = link_obj.get("scheme", 0) 
        
        # --- 🎯 Clean tokenApi logic to remove backslashes ---
        token_api_raw = link_obj.get("tokenApi", "")
        token_api_final = token_api_raw
        if isinstance(token_api_raw, str) and (token_api_raw.startswith("{") or token_api_raw.startswith("[")):
            try:
                # Convert stringified JSON to a proper JSON Object
                token_api_final = json.loads(token_api_raw)
            except:
                token_api_final = token_api_raw

        # Handle 'Link 1' replacement logic
        if original_name == "Link 1" and "file.genoads.com/ch1.m3u8" in link_val:
            final_title = "Ivan-FluX"
            final_link = "https://fallback-video.ivan-fluxo.workers.dev/video/index.m3u8"
        else:
            # Branding logic: Add SPORTIFy prefix or replace CricZ
            bare_qualities = ["AQ", "LQ", "SD", "HD", "FHD", "4K", "AD", "LOW", "MED", "HIGH"]
            if original_name.upper() in bare_qualities:
                final_title = f"SPORTIFy {original_name}"
            else:
                final_title = original_name.replace("CricZ", "SPORTIFy").replace("cricz", "SPORTIFy")
            
            # Domain replacement logic (.ok. -> .cf.)
            final_link = link_val.replace(".ok.", ".cf.") if "otte.live.ok.ww.aiv-cdn.net" in link_val else link_val

        # Standardize link object matching your requirements
        standard_link = OrderedDict([
            ("title", final_title),
            ("link", final_link),
            ("logo", ""),
            ("type", stream_type),
            ("api", link_obj.get("api", "")),
            ("tokenApi", token_api_final) # Now contains clean structured data
        ])
        final_list.append(standard_link)
    return final_list

def encrypt_json(data_dict):
    """Encrypts the structured JSON data using AES-EAX."""
    key = AES_SECRET.strip().encode()[:32]
    cipher = AES.new(key, AES.MODE_EAX)
    json_text = json.dumps(data_dict, ensure_ascii=False)
    ciphertext, tag = cipher.encrypt_and_digest(json_text.encode('utf-8'))
    return base64.b64encode(cipher.nonce + tag + ciphertext).decode('utf-8')

def run():
    if not AES_SECRET or not TARGET_URL:
        print("Error: Required GitHub Secrets are missing!")
        exit(1)

    token = get_token()
    # Payload logic matching the source app
    payload = json.dumps({"requestData": token, "from": "events"}, separators=(',', ':'))
    headers = {"User-Agent": "okhttp/4.9.0", "Content-Type": "application/json"}

    try:
        r = requests.post(TARGET_URL, data=payload, headers=headers, timeout=30)
        r.raise_for_status()
        raw_data = r.json()
        
        # Calculate Current Time in IST (UTC+5:30)
        now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
        
        events_list = []
        live_count, upcoming_count, finish_count = 0, 0, 0

        for item in raw_data:
            event_info = json.loads(item.get("event", "{}"))
            match_title = event_info.get("eventName") or event_info.get("seriesName") or "Unknown"
            
            # Date/Time Parsing for Status Logic
            start_str = f"{format_match_date(event_info.get('date', ''))} {event_info.get('time', '')}"
            end_str = f"{format_match_date(event_info.get('end_date', ''))} {event_info.get('end_time', '')}"
            
            status = "Upcoming"
            try:
                start_dt = datetime.datetime.strptime(start_str, "%Y/%m/%d %H:%M:%S")
                end_dt = datetime.datetime.strptime(end_str, "%Y/%m/%d %H:%M:%S")
                if now_ist < start_dt:
                    status = "Upcoming"; upcoming_count += 1
                elif start_dt <= now_ist <= end_dt:
                    status = "Live"; live_count += 1
                else:
                    status = "Finish"; finish_count += 1
            except: 
                upcoming_count += 1

            # Match object construction with your specific hierarchy
            match_obj = OrderedDict([
                ("id", int(item.get("id", 0))),
                ("title", match_title),
                ("image", event_info.get("eventLogo", "")),
                ("cat", event_info.get("category", "Sports")),
                ("eventInfo", OrderedDict([
                    ("teamA", event_info.get("teamAName", "Team A")),
                    ("teamB", event_info.get("teamBName", "Team B")),
                    ("teamAFlag", event_info.get("teamAFlag", "")),
                    ("teamBFlag", event_info.get("teamBFlag", "")),
                    ("eventName", match_title),
                    ("isHot", "0"),
                    ("Status", status),
                    ("startTime", f"{start_str} +0000"),
                    ("endTime", f"{end_str} +0000")
                ])),
                ("channels_data", process_links(item.get("links", "[]")))
            ])
            events_list.append(match_obj)

        # Sorting Logic: Live first, then Upcoming, then Finish
        priority = {"Live": 1, "Upcoming": 2, "Finish": 3}
        events_list.sort(key=lambda x: priority.get(x["eventInfo"]["Status"], 4))

        # Final Header and Counts
        update_time_str = now_ist.strftime("%I:%M:%S %p %d-%m-%Y")
        final_wrapped = OrderedDict([
            (" NAME ", "FluX-oW Live event ( Auto updated)"),
            ("AUTHOR", "iVan_FluX"),
            ("CONTACT (OWNER)", "https://t.me/iVan_flux"),
            ("TELEGRAM CHANNEL", "https://t.me/api_hub_by_ivan"),
            ("Last update time", update_time_str),
            ("Live", str(live_count).zfill(2)),
            ("Upcoming", str(upcoming_count).zfill(2)),
            ("Finish", str(finish_count).zfill(2)),
            ("events", events_list)
        ])

        # AES Encryption and File Storage
        encrypted_data = encrypt_json(final_wrapped)
        with open("Ivan-FluX.json", "w", encoding="utf-8") as f:
            json.dump({"data": encrypted_data}, f, indent=4)
        
        print(f"Success: Ivan-FluX.json created. (L:{live_count} U:{upcoming_count} F:{finish_count})")

    except Exception as e:
        print(f"Critical Error: {e}")
        exit(1)

if __name__ == "__main__":
    run()
