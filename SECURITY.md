# Security Policy

## Supported Versions

EchoPosture is an early-stage desktop application. Security fixes are provided for the latest published GA release.
Older GA, TEAM_ALPHA, DEV, and source snapshots may be used for historical comparison, but they do not receive
guaranteed security updates.

| Release | Security support |
| --- | --- |
| Latest GA release | Supported |
| Older releases and prereleases | Not supported |

Users should reproduce a suspected vulnerability with the latest GA release before reporting it when it is safe to
do so.

## Reporting a Vulnerability

Do not disclose an unpatched vulnerability in a public issue, pull request, discussion, log, screenshot, or other
public channel.

Use [GitHub private vulnerability reporting](https://github.com/NOVVLA/EchoPosture/security/advisories/new) to send
the report privately to the maintainers. Include as much of the following information as possible:

- The affected EchoPosture version, commit, or release package.
- Windows version and relevant runtime or dependency versions.
- A clear description of the impact and the conditions required to trigger it.
- Reproduction steps or a minimal proof of concept.
- Whether exploitation requires local access, user interaction, camera access, or elevated privileges.
- Any known workaround, evidence of active exploitation, or planned disclosure date.
- Whether you want to be credited in the advisory.

Remove personal camera images, credentials, tokens, private paths, and unrelated diagnostic data before attaching
evidence. If a report concerns a vulnerable third-party dependency, explain how it affects EchoPosture rather than
only linking to the upstream advisory.

## Response Process

The maintainers use the following response targets. They are goals rather than contractual service-level guarantees:

- Acknowledge a complete report within three business days.
- Perform an initial severity and reproducibility assessment within seven calendar days.
- Provide a status update at least every fourteen calendar days while a confirmed report remains unresolved.
- Prioritize actively exploited and critical vulnerabilities ahead of routine development and dependency updates.

After validation, the maintainers will coordinate remediation and disclosure with the reporter. Depending on impact,
the resolution may include a patch, dependency update, mitigation guidance, GitHub Security Advisory, CVE request,
and a new signed or hashed release artifact. Public disclosure should wait until a fix or practical mitigation is
available, unless earlier disclosure is necessary to protect users.

A report may be closed when it cannot be reproduced, does not cross a security boundary, affects only an unsupported
version, or is solely an upstream issue with no EchoPosture-specific impact. The maintainers will explain the reason
privately.

## Dependency and Vulnerability Maintenance

EchoPosture uses GitHub Dependabot for scheduled Python dependency and GitHub Actions version checks. The maintainers
will:

- Review Dependabot alerts when notified and perform a broader alert review at least weekly.
- Give critical and high-severity findings priority based on exploitability and EchoPosture's actual exposure.
- Require dependency update pull requests to pass the repository's applicable quality and Windows build checks.
- Record the reason when a relevant alert is dismissed, deferred, or accepted as a temporary risk.
- Publish security-relevant dependency changes through the normal audited release process when users need a new build.

Automated update pull requests do not by themselves prove that an update is safe. Runtime behavior, MediaPipe and
OpenCV compatibility, PyQt packaging, native launcher builds, and release contents still require risk-appropriate
verification.

## Safe Harbor

Good-faith research that avoids privacy violations, data destruction, service disruption, persistence, and access to
other people's systems is welcome. Stop testing and report immediately if you encounter sensitive user data. Do not
use a vulnerability to access camera data or systems that you do not own or have explicit permission to test.
