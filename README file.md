# Aditya-L1 Solar Flare Nowcasting Engine

### BETA_NOWCASTER
An automated, real-time data processing pipeline that ingests Level-1 telemetry from India's first dedicated solar mission (**Aditya-L1**) to detect solar flares and catalog cross-payload event dynamics in real time.

---

## 👥 Authors & Collaborators
* **Kishore** ([GitHub](https://github.com/)) 
* **Manasa** ([GitHub](https://github.com/VGManasa))
* **Shruthi** ([GitHub](https://github.com/Shruthi-Narayanan-web)) 

---

##  Overview & Scientific Motivation

Solar flares release up to $10^{32}\text{ ergs}$ of energy in minutes, posing immediate risks to satellite electronics, telecommunication networks, and power grids on Earth. 

This engine implements a real-time stream processing architecture to jointly analyze data from two critical onboard spectrometers:
1. **SoLEXS** (Solar Low Energy X-ray Spectrometer, 2–22 keV) — Captures thermal responses.
2. **HEL1OS** (High Energy L1 Orbiting X-ray Spectrometer, 8–150 keV) — Captures non-thermal particle acceleration.

### The Neupert Effect Integration
The pipeline is scientifically grounded in the **Neupert Effect**, which dictates that the time derivative of the soft X-ray (SXR) flux is directly proportional to the hard X-ray (HXR) flux during the impulsive phase of a flare:

$$\frac{dF_{\text{SXR}}(t)}{dt} \propto F_{\text{HXR}}(t)$$

Because SXR emissions track the cumulative thermal response of plasma heated by precipitating electrons, **HEL1OS typically peaks minutes before SoLEXS**. This system dynamically tracks this difference (the **"Neupert Lag"**), transforming raw data streams into immediately science-ready event records.

---

##  Core Engine Architecture

<img width="1600" height="872" alt="image" src="https://github.com/user-attachments/assets/fd8dd609-2e9c-4b59-8e07-9afc6e448fd7" />


