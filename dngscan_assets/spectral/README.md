# dngscan spectral calibration CSVs

These CSV files are replaceable calibration inputs for `tools/calibrate_skin_matrix.py`.
They intentionally keep measured or digitized spectral data outside the algorithm.

Current files are bootstrap-quality approximations, not authoritative measurements:

- `arri_alexa_alev3_ssf_digitized.csv`: rough ALEV3/ALEXA SSF digitization target. Replace with points digitized from Figure 1 of Leonhardt & Brendel, CIC 2015: https://library.imaging.org/admin/apis/public/api/ist/website/downloadArticle/cic/23/1/art00029
- `sony_imx410_qe_zwo_asi2400mc_digitized.csv`: rough IMX410 RGB QE proxy. Replace with points digitized from the ZWO ASI2400MC QE graph/specification: https://www.zwoastro.com/product/asi2400mc-pro/
- `sigma_fp_hot_mirror_model_420_660.csv`: sigmoid hot-mirror transmission model, 420nm blue-side and 660nm red-side cutoff assumption. Replace with measured transmission if available. Kolari teardown confirms the fp conversion/filter-stack context: https://kolarivision.com/the-sigma-fp-disassembly-and-teardown/
- `demo_skin_reflectance.csv`: analytic demo skin reflectance manifold. Replace with a licensed/public skin reflectance library such as Hyper-Skin if you have permission to use the released data: https://github.com/hyperspectral-skin/Hyper-Skin-2023
- `demo_cyan_reflectance.csv`: analytic cyan/blue-green material manifold. Replace or augment with measured surface spectra. The MLS dataset is one open source of real measured object/illumination spectra under CC BY-SA 4.0: https://github.com/visillect/mls-dataset

Accepted formats include wide `wavelength_nm,sample_1,sample_2,...`, tidy `sample,wavelength_nm,reflectance`, and single `wavelength_nm,value` CSVs.
