# CDC BMI reference setup and calculation

This app uses the CDC 2000 LMS method up to the age/sex-specific P95 and the CDC
2022 extended method above P95. It does not extrapolate outside ages 24 to under
240 months. It does not use the weight-for-age Z-score as a BMI percentile.

Official reference:
https://www.cdc.gov/growthcharts/extended-bmi-data-files.htm
CSV:
https://www.cdc.gov/growthcharts/data/extended-bmi/bmi-age-2022.csv
Infant guidance:
https://www.cdc.gov/growth-chart-training/hcp/using-growth-charts/who-using.html

## One-time setup in Admin
Open Admin using your existing second password. Expand BMI reference data.
Click Load / refresh public CDC BMI reference, or download the CSV above in your
browser and upload it through that panel. Only the public CSV goes to the app.
No patient measurements are sent to CDC, GitHub or any calculation service.

The complete official CSV could not be downloaded in the build environment, so
it is not bundled. The formula was checked against CDC's published worked examples.
Do not create a partial or fabricated reference file. The importer requires both
sexes and all 432 monthly rows, valid numeric parameters and known reference anchors.

A downloaded table is local to the hosting filesystem. A redeploy may remove it.
To keep it across redeployments, download the official CSV and put it in your code
repository at data/cdc_bmi_age_2022.csv. This is public reference data only. Never
put patient data or private Secrets into that folder or repository. Once this
file is present, the app reads it locally, without runtime downloads.

## Inputs
Use the recorded BMI with units kg/m². Provide age at the BMI measurement as total
months or as years AND months, plus explicit Male or Female growth-chart sex.
A whole-year age alone is sufficient for display but not a percentile. An age in
days or weeks can identify an infant but is not silently converted to an exact
month for the CDC table. DOB is not required or retained.

The reference uses one monthly bin: 48.5 represents 48 <= age < 49 months.
For BMI <= P95, z = ((BMI/M)^L - 1)/(L*S), or ln(BMI/M)/S if L=0.
Percentile = 100*Phi(z).
For BMI > P95, percentile = 90 + 10*Phi((BMI - P95)/sigma).
Intermediate calculations use full floating-point precision. Final display rounds
to one decimal, with <0.1 or >99.9 for the extreme tails rather than 0 or 100.

Published example checks:
Girl, age 114.5 months, BMI 21.2, L=-2.257782149, M=16.57626713,
S=0.132796819, P95=22.3979 -> 92.2414th percentile.
Boy, age 50.5 months, BMI 22.6, P95=17.8219, sigma=2.398288 -> 99.7683rd percentile.

The BMI itself remains displayed if percentile calculation is unavailable.
For children younger than 2 years, CDC does not recommend BMI-for-age for clinical
growth assessment. The app therefore does not calculate it for infants. At age 20
or older it reports no pediatric percentile. No weight category or diagnosis is
inferred. Measurement errors, timing mismatches and clinical context still require
review by the treating team.
