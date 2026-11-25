
USE pharma_counterfeit_db;

-- 1. run detection for the first time
CALL run_detection();

-- 2. inspect detected findings by rule and severity
SELECT
    rule_code,[
  {
    "rule_code": "HANDLER_UNLICENSED",
    "severity": "HIGH",
    "total_flags": "668"
  },
  {
    "rule_code": "LOT_COA_NOT_VERIFIED",
    "severity": "HIGH",
    "total_flags": "2"
  },
  {
    "rule_code": "LOT_OVERWEIGHT",
    "severity": "HIGH",
    "total_flags": "1"
  },
  {
    "rule_code": "LOT_UNDERWEIGHT",
    "severity": "LOW",
    "total_flags": "8"
  },
  {
    "rule_code": "MISSING_PACK",
    "severity": "MEDIUM",
    "total_flags": "192"
  },
  {
    "rule_code": "SOLD_TWICE",
    "severity": "CRITICAL",
    "total_flags": "70"
  },
  {
    "rule_code": "STAGE_SKIPPED",
    "severity": "HIGH",
    "total_flags": "63"
  },
  {
    "rule_code": "SUPPLIER_UNLICENSED",
    "severity": "HIGH",
    "total_flags": "5"
  },
  {
    "rule_code": "UNKNOWN_SERIAL",
    "severity": "CRITICAL",
    "total_flags": "256"
  }
]
    severity,
    COUNT(*) AS total_flags
FROM anomaly_flag
GROUP BY rule_code, severity
ORDER BY rule_code, severity;

-- 3. inspect the latest detection findings
SELECT
    flag_id,
    rule_code,
    serial_no,
    shipment_id,
    link_id,
    event_id,
    lot_id,
    severity,
    detected_at
FROM anomaly_flag
ORDER BY flag_id DESC
LIMIT 30;

-- 4. record the total number of flags
SELECT COUNT(*) AS flags_before_second_run
FROM anomaly_flag;

-- 5. run detection again to check duplicate prevention
CALL run_detection();

-- 6. compare the total number of flags after the second run
SELECT COUNT(*) AS flags_after_second_run
FROM anomaly_flag;

-- 7. inspect the rule-wise detection totals again
SELECT
    rule_code,
    COUNT(*) AS total_flags
FROM anomaly_flag
GROUP BY rule_code
ORDER BY rule_code;
