# search should include completed items in the resultes

Currently, search does not appear to include completed items. 

Search should be a fuzzy search that matches the first part of the slug, even if the user didn't include dashes, and without case sensitifity, and without trying to match punctuation. Punctuation should be ignored in the search to include more results.

## Solution

Updated search to always include completed items and use fuzzy matching that strips dashes/punctuation and is case-insensitive.

---
**Completed in commit:** `a5e9f5b`
