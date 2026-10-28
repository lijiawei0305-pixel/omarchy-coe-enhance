# Security reporting

Do not post API keys, private endpoints, raw recordings, transcripts, credential files, or configuration backups in public issues.

Report vulnerabilities privately through [GitHub private vulnerability reporting](https://github.com/lijiawei0305-pixel/omarchy-coe-voice-typing/security/advisories/new). Include the affected commit/version and minimal reproduction with mock credentials. For ordinary bugs, use Issues with a sanitized report.

The latest release is the supported security baseline. There is no hosted backend: your configured ASR/LLM services receive the submitted data under their own policies. Audio and transcript history are not persisted by default. Local credential and backup directories are deliberately excluded from Git.
