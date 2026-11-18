# Embedding A/B test

Database: `data/snap_v3_rehearsal.duckdb`; CPU; DuckDB memory limit 4 GB. Identifiers were stripped for the AFSL/credit runs, with ABN/ACN printed by the register as truth.

| model | source | precision | recall | links (NAME_SEMANTIC) | wall | embedding |
|---|---|---:|---:|---:|---:|---:|
| all-MiniLM-L6-v2 | asic_afsl | 100.0% (6691/6691) | 96.8% (6691/6913) | 6692 (0) | 60.54 s | 10.05 s |
| all-MiniLM-L6-v2 | asic_credit | 100.0% (4033/4033) | 89.1% (4033/4525) | 4033 (0) | 41.89 s | 6.40 s |
| bge-small-en-v1.5 | asic_afsl | 100.0% (6691/6691) | 96.8% (6691/6913) | 6691 (0) | 57.60 s | 18.33 s |
| bge-small-en-v1.5 | asic_credit | 100.0% (4033/4033) | 89.1% (4033/4525) | 4033 (0) | 48.22 s | 11.05 s |

Cosine (MiniLM / BGE): unrelated pairs CBA-Commonwealth Superannuation Corporation 0.3053 / 0.5614; Westpac Banking Corporation-Westpac Securities 0.8226 / 0.8649; AMP Capital-AMP Limited 0.5556 / 0.8085; Rio Tinto plc-Rio Tinto Limited 0.8472 / 0.9634. True-match pairs: Suntax 0.9169 / 0.9310; Lee Valley 0.9074 / 0.9062; A1 Financial 1.0000 / 1.0000; Carbon Neutral 0.4439 / 0.7427; Wedgetail 0.4887 / 0.6897.

Rehearsal (200 rows): both models resolved 128/128 correctly, precision 100.0%, recall 68.1% (128/188), 72 abstentions, 0 wrong links. Wall time was 36.41 s MiniLM and 41.69 s BGE. Recommendation: retain MiniLM. BGE is not at least as good on AFSL recall, raises unrelated-pair cosine, and costs more embedding time. Both are local; cost USD 0.
