"""
Fictional documentation corpus for RAG retrieval/grounding evals.

Domain: a fictional protein-sequencing instrument platform ("NanoSeq X1" by
"Helix Analytics") -- chosen to mirror the kind of systems-integration
documentation (APIs, services, hardware/software boundaries, run lifecycle)
you'd actually find at an instrumentation company, while staying entirely
fictional so nothing here is confidential or trademarked.

Design notes (why 18 docs instead of 5):

  - A 5-document corpus with top_k=2/3 retrieves 40-60% of the whole
    knowledge base on every query -- there's no way for retrieval to
    meaningfully "miss." With ~18 docs and top_k=1-2, retrieval has to make
    a real choice, so a retrieval-recall failure can actually happen and be
    caught by an eval.
  - Several docs are deliberately "near-topic distractors": different
    services that share vocabulary (Service, API, queue, endpoint, status
    code) with the doc you actually want, so cosine similarity has to do
    real discriminative work instead of trivially separating unrelated
    topics.
  - Doc 8 (Reagent Inventory) is the one used for the vocabulary-mismatch
    test: it's phrased in domain jargon ("cartridge", "buffer stock",
    "sequencing run") while the eval question is phrased in plain language
    ("not sure there's enough reagent left"), so embedding similarity isn't
    guaranteed to rank it first.
  - Nothing in this corpus mentions GraphQL, gRPC, or SOAP -- those stay
    useful as "genuinely not in the docs" grounding-refusal probes.
"""

CORPUS = [
    # 0
    "The Run Service exposes a REST API at /api/runs. POST /api/runs starts "
    "a new sequencing run on the NanoSeq X1; GET /api/runs/{id} returns run "
    "status, elapsed time, and current cycle number.",

    # 1
    "Authentication for all NanoSeq X1 instrument APIs uses OAuth2 client "
    "credentials flow. Access tokens expire after 60 minutes and must be "
    "refreshed using the /api/auth/refresh endpoint before they lapse.",

    # 2
    "The Run Service publishes a 'run.completed' event to an internal "
    "message queue when a sequencing run finishes, including the run ID, "
    "total cycles executed, and final QC score.",

    # 3
    "API rate limits for the NanoSeq X1 control plane are 60 requests per "
    "minute per instrument serial number. Exceeding this returns HTTP 429 "
    "with a Retry-After header.",

    # 4
    "The Sample Prep Service tracks chip loading status. A chip must report "
    "'loaded' and pass the automated seal-integrity check before the Run "
    "Service will accept a start-run request for that chip.",

    # 5
    "The Base Calling Service converts raw optical signal traces into "
    "called bases and per-base quality scores. It runs as a separate "
    "process from the Run Service and reads directly from the instrument's "
    "local signal buffer.",

    # 6
    "Firmware updates for the NanoSeq X1 are delivered as signed .fwpkg "
    "files. The instrument verifies the signature before applying an "
    "update and will refuse to install an unsigned or corrupted package.",

    # 7
    "The Calibration Service must complete an optical alignment check "
    "within 24 hours before a run; if the last successful calibration is "
    "older than that, the Run Service blocks new runs until recalibration.",

    # 8
    "The Reagent Inventory Service must be queried before a sequencing run "
    "is initiated to confirm that cartridge and buffer stock levels are "
    "sufficient for the requested run length.",

    # 9
    "Reagent cartridges are tracked by lot number and expiration date. The "
    "Reagent Inventory Service will reject a run start request if the "
    "loaded cartridge's expiration date has passed.",

    # 10
    "The Data Export Service uploads completed run results to customer-"
    "configured cloud storage (S3 or GCS buckets) once QC passes. Exports "
    "are retried up to 3 times on transient network failure.",

    # 11
    "The LIMS Integration Service can push completed run metadata "
    "(sample ID, run ID, QC score, timestamp) to a customer's laboratory "
    "information management system via a configurable webhook.",

    # 12
    "The Notification Service sends email or Slack alerts on run "
    "completion, calibration expiry, and reagent-low warnings, based on "
    "per-user notification preferences configured in the instrument UI.",

    # 13
    "User accounts on the NanoSeq X1 instrument UI have one of three "
    "roles: Operator (can start/stop runs), Administrator (can also manage "
    "users and calibration schedules), and Viewer (read-only access to "
    "run history and reports).",

    # 14
    "The instrument's local network interface supports static IP "
    "configuration or DHCP. Remote API access must be explicitly enabled "
    "in the network settings panel; it is disabled by default on new "
    "installs for security.",

    # 15
    "QC scoring for a completed run combines mean read length, percent "
    "reads passing filter, and mean quality score into a single 0-100 "
    "composite score shown on the run summary screen.",

    # 16
    "The instrument logs all API requests, run state transitions, and "
    "error events to a local rotating log file, retained for 90 days by "
    "default. Log retention is configurable in system settings.",

    # 17
    "Error code E-104 indicates a seal-integrity failure on chip loading. "
    "Error code E-207 indicates the optical alignment drifted out of "
    "tolerance mid-run and the run was auto-aborted.",
]
