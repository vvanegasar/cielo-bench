# Verified references

All checks were made on 2026-11-23 (Colombia time). A reference is in `references.bib` only if its record was opened and its title, authors and year matched.

How each record was opened:

- **arXiv**: the arXiv metadata API record for the id (`export.arxiv.org/api/query?id_list=…`), which is the same record the abstract page shows. The URL column gives the abstract page. Venue is stated only when the arXiv record's comment or journal-ref field states it.
- **DOI**: the Crossref record for the DOI (`api.crossref.org/works/<doi>`). The URL column gives the DOI link.
- **Other**: stated in the row.

Depth of reading. Six papers were read in full by the related-work check (marked ‡): Waqas et al., Zhao et al., Mao et al., Sethi et al., FaulT-Bench (Tseng et al.) and Failure-Transparent Agents (Zhu et al.). The other recent papers closest to this work (marked †) were read as abstracts or methods sections. The eight arXiv entries added in the review were supplied as verified by the project lead and re-checked here against the arXiv metadata API (title, authors, date, comment).

Bib keys use the arXiv year for arXiv-only entries and the venue year for entries published in a venue.

## Sycophancy

| Key | Title | Authors | Year | Venue / id | Verified at |
|---|---|---|---|---|---|
| `perez2023discovering` | Discovering Language Model Behaviors with Model-Written Evaluations | Perez, Ringer, Lukošiūtė, Nguyen, Chen, Heiner, Pettit, Olsson, Kundu, Kadavath, et al. (63 authors) | 2023 | Findings of ACL 2023, pp. 13387–13434; arXiv:2212.09251 | https://doi.org/10.18653/v1/2023.findings-acl.847 and https://arxiv.org/abs/2212.09251 |
| `sharma2023sycophancy` | Towards Understanding Sycophancy in Language Models | Sharma, Tong, Korbak, Duvenaud, Askell, Bowman, Cheng, Durmus, Hatfield-Dodds, Johnston, Kravec, Maxwell, McCandlish, Ndousse, Rausch, Schiefer, Yan, Zhang, Perez | 2023 | arXiv:2310.13548 | https://arxiv.org/abs/2310.13548 |
| `wei2023simple` | Simple synthetic data reduces sycophancy in large language models | Wei, Huang, Lu, Zhou, Le | 2023 | arXiv:2308.03958 | https://arxiv.org/abs/2308.03958 |
| `malmqvist2024sycophancy` | Sycophancy in Large Language Models: Causes and Mitigations | Malmqvist | 2024 | arXiv:2411.15287 | https://arxiv.org/abs/2411.15287 |
| `fanous2025syceval` | SycEval: Evaluating LLM Sycophancy | Fanous, Goldberg, Agarwal, Lin, Zhou, Daneshjou, Koyejo | 2025 | arXiv:2502.08177 (record comment: AIES 2025) | https://arxiv.org/abs/2502.08177 |
| `cheng2025elephant` | ELEPHANT: Measuring and understanding social sycophancy in LLMs | Cheng, Yu, Lee, Khadpe, Ibrahim, Jurafsky | 2025 | arXiv:2505.13995 | https://arxiv.org/abs/2505.13995 |
| `laban2023flipflop` | Are You Sure? Challenging LLMs Leads to Performance Drops in The FlipFlop Experiment | Laban, Murakhovs'ka, Xiong, Wu | 2023 | arXiv:2311.08596 | https://arxiv.org/abs/2311.08596 |
| `ranaldi2023contradict` | When Large Language Models contradict humans? Large Language Models' Sycophantic Behaviour | Ranaldi, Pucci | 2023 | arXiv:2311.09410 | https://arxiv.org/abs/2311.09410 |
| `petrov2025brokenmath` | BrokenMath: A Benchmark for Sycophancy in Theorem Proving with LLMs | Petrov, Dekoninck, Vechev | 2025 | arXiv:2510.04721 | https://arxiv.org/abs/2510.04721 |
| `hong2025sycon` † | Measuring Sycophancy of Language Models in Multi-turn Dialogues | Hong, Byun, Kim, Shu, Choi | 2025 | Findings of EMNLP 2025, pp. 2239–2259 (arXiv journal-ref); arXiv:2505.23840 | https://arxiv.org/abs/2505.23840 |
| `tang2026spine` † | SPINE: Measuring LLM Sycophancy under Sustained Multi-Turn Pressure | Tang, Wei, Jiang, Huang | 2026 | arXiv:2609.09090 | https://arxiv.org/abs/2609.09090 |

## Sycophancy, deference and tool evidence in agents

| Key | Title | Authors | Year | Venue / id | Verified at |
|---|---|---|---|---|---|
| `waqas2025acc` ‡ | Assertion-Conditioned Compliance: A Provenance-Aware Vulnerability in Multi-Turn Tool-Calling Agents | Waqas, Golthi, Hayashida, Mao | 2025 | arXiv:2512.00332 | https://arxiv.org/abs/2512.00332 |
| `zhao2026price` ‡ | The Price of Agreement: Measuring LLM Sycophancy in Agentic Financial Applications | Zhao, Balagopalan, Agrawal, Yergasheva, Alshikh, Bikel | 2026 | arXiv:2604.24668 (record comment: accepted to ICLR 2026 FinAI Workshop) | https://arxiv.org/abs/2604.24668 |
| `mao2026cave` ‡ | "You're Right, Let Me Fix It": How LLM Agents Damage Correct Work When Falsely Accused | Mao, Qian, Wang, Yi, Li, Chen, Gao, Zheng, Wang | 2026 | arXiv:2609.32616 | https://arxiv.org/abs/2609.32616 |
| `zhang2026agentdecept` † | AgentDecept: Benchmarking Deceptive Behavior in Tool-Using LLM Agents under Pressure | Zhang, Yan, Yin, Kuo, Jiang, Ouyang, Liu, Wang | 2026 | arXiv:2610.39377 | https://arxiv.org/abs/2610.39377 |
| `xie2023chameleon` | Adaptive Chameleon or Stubborn Sloth: Revealing the Behavior of Large Language Models in Knowledge Conflicts | Xie, Zhang, Chen, Lou, Su | 2023 | arXiv:2305.13300 (record comment: ICLR 2024 Spotlight) | https://arxiv.org/abs/2305.13300 |
| `yang2026overreliance` † | Agents' Overreliance on Unreliable Tools | Yang, Song, Kim, Song, Park, Jo | 2026 | arXiv:2609.05587 | https://arxiv.org/abs/2609.05587 |
| `tseng2026faultbench` ‡ | FaulT-Bench: Towards Benchmarking Network Troubleshooting LLM Agents under Unreliable User Tickets | Tseng, Bogahawatta, Ginige, Patel, Dakic, Seneviratne | 2026 | arXiv:2608.27021 | https://arxiv.org/abs/2608.27021 |
| `wu2026xyeval` † | XYEval: Agents say yes to bad advice | Wu, Li, Tafjord, Kim | 2026 | arXiv:2609.23939 | https://arxiv.org/abs/2609.23939 |
| `varlamov2026memtoc` † | MemToC: Benchmarking Memory-Tool Conflict Resolution in Large Language Models | Varlamov, Zinnatullin, Rykov, Panchenko, Alimova | 2026 | arXiv:2608.26295 | https://arxiv.org/abs/2608.26295 |
| `kumar2026authority` † | Authority Bias in Language Models: Source Deference and User Agreement Are Not Interchangeable | Kumar, Chopra | 2026 | arXiv:2609.37616 (record comment: accepted at NeurIPS 2026, main conference) | https://arxiv.org/abs/2609.37616 |

## False premises and presuppositions

| Key | Title | Authors | Year | Venue / id | Verified at |
|---|---|---|---|---|---|
| `yu2023crepe` | CREPE: Open-Domain Question Answering with False Presuppositions | Yu, Min, Zettlemoyer, Hajishirzi | 2023 | ACL 2023 (Long Papers), pp. 10457–10480; arXiv:2211.17257 | https://doi.org/10.18653/v1/2023.acl-long.583 and https://arxiv.org/abs/2211.17257 |
| `kim2022qa2` | (QA)^2: Question Answering with Questionable Assumptions | Kim, Htut, Bowman, Petty | 2022 | arXiv:2212.10003 (record comment: ACL 2023 camera-ready) | https://arxiv.org/abs/2212.10003 |
| `hu2023falseqa` | Won't Get Fooled Again: Answering Questions with False Premises | Hu, Luo, Wang, Cheng, Liu, Sun | 2023 | arXiv:2307.02394 (record comment: accepted to ACL 2023 main conference) | https://arxiv.org/abs/2307.02394 |
| `vu2023freshllms` | FreshLLMs: Refreshing Large Language Models with Search Engine Augmentation | Vu, Iyyer, Wang, Constant, Wei, Wei, Tar, Sung, Zhou, Le, Luong | 2023 | arXiv:2310.03214 | https://arxiv.org/abs/2310.03214 |
| `yuan2024whispers` | Whispers that Shake Foundations: Analyzing and Mitigating False Premise Hallucinations in Large Language Models | Yuan, Cao, Jin, Chen, Zeng, Liu, Zhao | 2024 | arXiv:2402.19103 | https://arxiv.org/abs/2402.19103 |
| `xie2026oversearching` † | Over-Searching in Search-Augmented Large Language Models | Xie, Gopinath, Qiu, Lin, Sun, Potdar, Dhingra | 2026 | arXiv:2601.05503 (record comment: accepted to EACL 2026 main conference) | https://arxiv.org/abs/2601.05503 |
| `xie2026hoprefusal` † | HopRefusalBench: Diagnosing Refusal Failures in Search-Augmented Agents for Multi-Hop Reasoning | Xie, Sun, Chen, Zheng, Liu, Song | 2026 | arXiv:2608.01358 | https://arxiv.org/abs/2608.01358 |

## Tool-use and agent benchmarks

| Key | Title | Authors | Year | Venue / id | Verified at |
|---|---|---|---|---|---|
| `li2023apibank` | API-Bank: A Comprehensive Benchmark for Tool-Augmented LLMs | Li, Zhao, Yu, Song, Li, Yu, Li, Huang, Li | 2023 | arXiv:2304.08244 (record comment: EMNLP 2023) | https://arxiv.org/abs/2304.08244 |
| `qin2023toolllm` | ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs | Qin, Liang, Ye, Zhu, Yan, Lu, Lin, Cong, Tang, Qian, Zhao, Hong, Tian, Xie, Zhou, Gerstein, Li, Liu, Sun | 2023 | arXiv:2307.16789 | https://arxiv.org/abs/2307.16789 |
| `liu2023agentbench` | AgentBench: Evaluating LLMs as Agents | Liu, Yu, Zhang, Xu, Lei, Lai, Gu, Ding, Men, Yang, Zhang, Deng, Zeng, Du, Zhang, Shen, Zhang, Su, Sun, Huang, Dong, Tang | 2023 | arXiv:2308.03688 (record comment: published in ICLR 2024) | https://arxiv.org/abs/2308.03688 |
| `mialon2023gaia` | GAIA: a benchmark for General AI Assistants | Mialon, Fourrier, Swift, Wolf, LeCun, Scialom | 2023 | arXiv:2311.12983 | https://arxiv.org/abs/2311.12983 |
| `yao2024taubench` | τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains | Yao, Shinn, Razavi, Narasimhan | 2024 | arXiv:2406.12045 | https://arxiv.org/abs/2406.12045 |
| `yu2018spider` | Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task | Yu, Zhang, Yang, Yasunaga, Wang, Li, Ma, Li, Yao, Roman, Zhang, Radev | 2018 | arXiv:1809.08887 (record comment: EMNLP 2018) | https://arxiv.org/abs/1809.08887 |
| `li2023bird` | Can LLM Already Serve as A Database Interface? A BIg Bench for Large-Scale Database Grounded Text-to-SQLs | Li, Hui, Qu, Yang, Li, Li, Wang, Qin, Cao, Geng, Huo, Zhou, Ma, Li, Chang, Huang, Cheng, Li | 2023 | arXiv:2305.03111 (record comment: NeurIPS 2023) | https://arxiv.org/abs/2305.03111 |
| `debenedetti2024agentdojo` | AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents | Debenedetti, Zhang, Balunović, Beurer-Kellner, Fischer, Tramèr | 2024 | arXiv:2406.13352 | https://arxiv.org/abs/2406.13352 |

## Abstention, hallucination and tool failure

| Key | Title | Authors | Year | Venue / id | Verified at |
|---|---|---|---|---|---|
| `yin2023know` | Do Large Language Models Know What They Don't Know? | Yin, Sun, Guo, Wu, Qiu, Huang | 2023 | arXiv:2305.18153 (record comment: Findings of ACL 2023) | https://arxiv.org/abs/2305.18153 |
| `wen2025abstention` | Know Your Limits: A Survey of Abstention in Large Language Models | Wen, Yao, Feng, Xu, Tsvetkov, Howe, Wang | 2025 | TACL 13, pp. 529–556; arXiv:2407.18418 | https://doi.org/10.1162/tacl_a_00754 and https://arxiv.org/abs/2407.18418 |
| `kirichenko2025abstentionbench` | AbstentionBench: Reasoning LLMs Fail on Unanswerable Questions | Kirichenko, Ibrahim, Chaudhuri, Bell | 2025 | arXiv:2506.09038 | https://arxiv.org/abs/2506.09038 |
| `chen2023rgb` | Benchmarking Large Language Models in Retrieval-Augmented Generation | Chen, Lin, Han, Sun | 2023 | arXiv:2309.01431 (record comment: accepted to AAAI 2024) | https://arxiv.org/abs/2309.01431 |
| `yoran2023robust` | Making Retrieval-Augmented Language Models Robust to Irrelevant Context | Yoran, Wolfson, Ram, Berant | 2023 | arXiv:2310.01558 | https://arxiv.org/abs/2310.01558 |
| `sun2024toolsfail` | Tools Fail: Detecting Silent Errors in Faulty Tools | Sun, Min, Chang, Bisk | 2024 | arXiv:2406.19228 | https://arxiv.org/abs/2406.19228 |
| `zhang2024toolbehonest` | ToolBeHonest: A Multi-level Hallucination Diagnostic Benchmark for Tool-Augmented Large Language Models | Zhang, Chen, Wang, Liu, Yang, Shi, Zhu, Lin, Wan, Yang, Sakai, Feng, Yamana | 2024 | arXiv:2406.20015 | https://arxiv.org/abs/2406.20015 |
| `huang2025critictool` | CRITICTOOL: Evaluating Self-Critique Capabilities of Large Language Models in Tool-Calling Error Scenarios | Huang, Fang, Chen, Yuan, Ye, Zeng, Chen, Mao, Zhao | 2025 | arXiv:2506.13977 | https://arxiv.org/abs/2506.13977 |
| `soni2026toolfailbench` † | ToolFailBench: Diagnosing Tool-Use Failures in LLM Agents | Soni | 2026 | arXiv:2607.04686 (record comment: published at the ICML 2026 workshops AIWILD and FAGEN) | https://arxiv.org/abs/2607.04686 |
| `sethi2026fabrication` ‡ | Fabrication After Tool Failure: Tool-Augmented Agents Assert Values Their Tools Did Not Return | Sethi, Kenzhebayev, Paturi, Raina, Raina, Sheth | 2026 | arXiv:2609.14758 | https://arxiv.org/abs/2609.14758 |
| `zhu2026fta` ‡ | Failure-Transparent Agents: Benchmarking Post-Failure Reporting in Tool-Using Language Models | Zhu, Xie, Chen, Ding, Tang, Qi, Fei | 2026 | arXiv:2609.35732 | https://arxiv.org/abs/2609.35732 |
| `liu2026agentabstain` † | AgentAbstain: Do LLM Agents Know When Not to Act? | Liu, Zhang, Kasprova, Rabbani, Zahraei, Zhang, Ebrahimpour-Boroojeny, Chandrasekaran | 2026 | arXiv:2607.10059 | https://arxiv.org/abs/2607.10059 |

## LLM judges

| Key | Title | Authors | Year | Venue / id | Verified at |
|---|---|---|---|---|---|
| `zheng2023judging` | Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena | Zheng, Chiang, Sheng, Zhuang, Wu, Zhuang, Lin, Li, Li, Xing, Zhang, Gonzalez, Stoica | 2023 | arXiv:2306.05685 (record comment: NeurIPS 2023 Datasets and Benchmarks Track) | https://arxiv.org/abs/2306.05685 |
| `thakur2025judging` | Judging the Judges: Evaluating Alignment and Vulnerabilities in LLMs-as-Judges | Thakur, Choudhary, Ramayapally, Vaidyanathan, Hupkes | 2025 | GEM² workshop 2025, pp. 404–430 (arXiv journal-ref, which links https://aclanthology.org/2025.gem-1.33/); arXiv:2406.12624 | https://arxiv.org/abs/2406.12624 |
| `panickssery2024selfpref` | LLM Evaluators Recognize and Favor Their Own Generations | Panickssery, Bowman, Feng | 2024 | arXiv:2404.13076 | https://arxiv.org/abs/2404.13076 |
| `wang2023notfair` | Large Language Models are not Fair Evaluators | Wang, Li, Chen, Cai, Zhu, Lin, Cao, Liu, Liu, Sui | 2023 | arXiv:2305.17926 | https://arxiv.org/abs/2305.17926 |

## Statistics for evaluations

| Key | Title | Authors | Year | Venue / id | Verified at |
|---|---|---|---|---|---|
| `miller2024errorbars` | Adding Error Bars to Evals: A Statistical Approach to Language Model Evaluations | Miller | 2024 | arXiv:2411.00640 | https://arxiv.org/abs/2411.00640 |
| `bowyer2025clt` | Position: Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints | Bowyer, Aitchison, Ivanova | 2025 | arXiv:2503.01747 (record comment: ICML 2025 Spotlight Position Paper) | https://arxiv.org/abs/2503.01747 |
| `dror2018hitchhiker` | The Hitchhiker's Guide to Testing Statistical Significance in Natural Language Processing | Dror, Baumer, Shlomov, Reichart | 2018 | ACL 2018 (Long Papers), pp. 1383–1392 | https://doi.org/10.18653/v1/P18-1128 |
| `card2020power` | With Little Power Comes Great Responsibility | Card, Henderson, Khandelwal, Jia, Mahowald, Jurafsky | 2020 | EMNLP 2020, pp. 9263–9274; arXiv:2010.06595 | https://doi.org/10.18653/v1/2020.emnlp-main.745 and https://arxiv.org/abs/2010.06595 |
| `wilson1927probable` | Probable Inference, the Law of Succession, and Statistical Inference | Wilson | 1927 | JASA 22(158), pp. 209–212 | https://doi.org/10.1080/01621459.1927.10502953 |
| `brown2001interval` | Interval Estimation for a Binomial Proportion | Brown, Cai, DasGupta | 2001 | Statistical Science 16(2), pp. 101–133 | https://doi.org/10.1214/ss/1009213286 |
| `mcnemar1947note` | Note on the Sampling Error of the Difference Between Correlated Proportions or Percentages | McNemar | 1947 | Psychometrika 12(2), pp. 153–157 | https://doi.org/10.1007/BF02295996 |
| `connor1987sample` | Sample Size for Testing Differences in Proportions for the Paired-Sample Design | Connor | 1987 | Biometrics 43(1), pp. 207–211 (Crossref gives the first page; the range is from PubMed, PMID 3567305, per the project lead) | https://doi.org/10.2307/2531961 |
| `field2007bootstrapping` | Bootstrapping Clustered Data | Field, Welsh | 2007 | JRSS Series B 69(3), pp. 369–390 | https://doi.org/10.1111/j.1467-9868.2007.00593.x |
| `cameron2008bootstrap` | Bootstrap-Based Improvements for Inference with Clustered Errors | Cameron, Gelbach, Miller | 2008 | Review of Economics and Statistics 90(3), pp. 414–427 | https://doi.org/10.1162/rest.90.3.414 |
| `holm1979simple` | A Simple Sequentially Rejective Multiple Test Procedure | Holm | 1979 | Scandinavian Journal of Statistics 6, pp. 65–70 | **Other:** added by decision of the project lead, with the JSTOR stable URL https://www.jstor.org/stable/4615733. The JSTOR page did not load in this session and `doi.org/10.2307/4615733` returns 404; the metadata was confirmed only in a secondary index (OpenAlex). Open the JSTOR page in a browser once before submission. |

## Data, documentation and software

| Key | Title | Authors | Year | Venue / id | Verified at |
|---|---|---|---|---|---|
| `gebru2021datasheets` | Datasheets for Datasets | Gebru, Morgenstern, Vecchione, Vaughan, Wallach, Daumé III, Crawford | 2021 | Communications of the ACM 64(12), pp. 86–92; arXiv:1803.09010 | https://doi.org/10.1145/3458723 and https://arxiv.org/abs/1803.09010 |
| `giorgini1996horizons` | JPL's On-Line Solar System Data Service | Giorgini, Yeomans, Chamberlin, Chodas, Jacobson, Keesey, Lieske, Ostro, Standish, Wimberly | 1996 | Bulletin of the American Astronomical Society 28(3), p. 1158 | **Other:** listed under "References for the Horizons system" in JPL's own manual, https://ssd.jpl.nasa.gov/horizons/manual.html. It has no DOI; the NASA ADS page did not load. See NOTES.md, decision 6. |
| `vanegas2026cielobench` | cielo-bench: Check or agree? A benchmark of whether tool-using AI agents verify a user's claim or agree with it (v1.1.0) | Vanegas Aristizábal | 2026 | Zenodo, concept DOI 10.5281/zenodo.24441942 | https://doi.org/10.5281/zenodo.24441942 resolves (HTTP 200, to `zenodo.org/records/24479081`); metadata from `CITATION.cff` |

**Count:** 65 external references and 1 software self-citation, 66 entries in `references.bib`. All 66 are cited in `main.tex`.

## Considered and left out

| Candidate | Why it is not cited |
|---|---|
| Cheng et al. (2026), "Sycophantic AI decreases prosocial intentions and promotes dependence", Science 391(6792) | The arXiv record of ELEPHANT (2505.13995) carries this DOI (10.1126/science.aec8352), but Crossref shows it is a different paper with a different author list. ELEPHANT is cited by its arXiv id only. |
| A web page claiming that ELEPHANT tests falsified code output | Unverified secondary source; not used. |
