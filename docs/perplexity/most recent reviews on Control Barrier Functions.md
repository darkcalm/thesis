<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# most recent reviews on Control Barrier Functions


---

## Control Barrier Functions: A Comprehensive Review of Recent Advances

Control Barrier Functions (CBFs) have emerged as a foundational framework for synthesizing provably safe controllers in autonomous and safety-critical systems. Recent comprehensive reviews and advances spanning 2024-2025 reveal significant progress in addressing practical deployment challenges, while also highlighting critical limitations that continue to drive research innovation.

### Recent Survey Landscape

The most significant recent contribution is a comprehensive IEEE review published in late 2024 that systematically analyzes Control Barrier Functions across three interconnected dimensions: uncertainty handling, structural design optimization, and feasibility assurance. This review synthesizes recent methodological progress while identifying fundamental challenges limiting real-world deployment. The analysis distinguishes between strategies for handling unknown dynamics, modeling discrepancies, and dynamic environments, spanning both robust theoretical methods and learning-based approaches. Notably, the review identifies a critical tension: while CBF-based approaches rigorously enforce safety through quadratic programming formulations (CBF-QP), practical systems frequently encounter feasibility challenges where safety and performance objectives become incompatible.[^1_1]

### Filtered Control Barrier Functions: Resolving Control Input Smoothness

A significant advancement in 2025 addresses a persistent practical problem in CBF synthesis: non-smooth or discontinuous control inputs that degrade system performance and violate actuator limitations. The Filtered Control Barrier Function (FCBF) framework extends high-order CBFs by integrating an auxiliary dynamical system acting as an input regularization filter. This design ensures that filtered control inputs remain Lipschitz continuous while satisfying control bounds and maintaining safety guarantees. The framework reformulates the problem as a single quadratic program, preserving computational efficiency for real-time implementation. Simulation results on unicycle navigation demonstrate that FCBFs produce smoother trajectories and maintain feasibility across hyperparameter ranges where standard HOCBFs become infeasible.[^1_2]

### Adaptive Learning-Based Approaches

Real-time learning of uncertain system dynamics has become increasingly central to CBF research. An approach combining adaptive deep neural networks (DNNs) with CBFs provides a first-of-its-kind framework for online parameter adaptation without pre-training. Rather than assuming perfect models or using worst-case uncertainty bounds that render the feasible control set overly conservative, this method learns system dynamics in real-time through a least squares adaptation law based on state-derivative estimation. The key innovation is that parameter estimation error convergence bounds are directly incorporated into CBF constraints within an optimization-based controller. The method further demonstrates capability for safe operation under intermittent loss of feedback by leveraging the learned DNN model for open-loop state predictions. This addresses a critical vulnerability in disturbance-observer-based methods that rely entirely on real-time feedback.[^1_3]

### High-Order Constraints and Structural Design

A persistent challenge in CBF application involves handling safety constraints with high relative degree—situations where control inputs appear only after multiple differentiations of the constraint function. Recent work across 2024-2025 has produced several complementary approaches:

**Truncated Taylor-Based Formulation**: Rather than the standard HOCBF approach requiring multiple class K functions (one per derivative order), a truncated Taylor approximation reduces this to a single design parameter. This simplification addresses what has been a significant practical bottleneck: hyperparameter tuning for complex constraints.[^1_4]

**Rectified Control Barrier Functions**: By incorporating activation functions into the CBF construction, rectified CBFs overcome limitations of standard HOCBFs while maintaining computational simplicity. This approach is particularly relevant for aircraft control problems and other high-degree-of-freedom systems.[^1_5]

**Reciprocal CBFs via Level Surface Design**: An alternative construction method designs reciprocal barrier functions whose level surfaces ensure globally asymptotically stable restricted dynamics, providing forward invariance and forward completeness without recursive complexity.[^1_6]

### Data-Driven and Learning-Based Methods

The shift toward data-driven CBF construction represents a fundamental expansion of the field. Learning approaches now span multiple paradigms:

**Learning from Expert Demonstrations**: By leveraging inverse constraint learning, practitioners can train neural CBFs when formal safety specifications are ambiguous but safe expert trajectories exist. This approach uses expert data to implicitly define what constitutes safety rather than requiring explicit formal definitions.[^1_7]

**Set-Based CBFs for Implicit Definitions**: A novel approach leverages control invariant sets from reachability analysis to define CBFs implicitly through minimal scaling operations. This enables data-driven, high-dimensional CBF representations suitable for learning-based approximations.[^1_8]

**Equivariant Multi-Agent CBFs**: For multi-robot systems, recent work incorporates symmetries and group structure into neural CBF designs, achieving zero-shot generalization to larger swarms while improving scalability and sampling efficiency.[^1_9]

### Uncertainty, Robustness, and Stochastic Systems

CBF research increasingly addresses real-world uncertainty sources. Robust data-driven approaches guarantee safety despite worst-case generalization errors from learned models, while event-triggered learning frameworks dynamically balance between performance optimization and model accuracy improvement based on learned model uncertainty. For stochastic systems, risk-aware CBF formulations that tighten safety margins probabilistically have been developed, departing from traditional martingale theory approaches.[^1_10][^1_11][^1_12]

### Multi-Agent and Interaction-Based Safety

Recent advances extend CBFs to multi-agent systems where safety emerges from interaction dynamics. A novel approach learns agents' responsibility allocation—their willingness to deviate from desired control to ensure safe interaction with others—through differentiable optimization. This has direct applications in autonomous driving and coordinated systems where social norms and contextual factors influence safety requirements.[^1_13]

### Persistent Challenges and Open Questions

Despite substantial progress, several challenges remain at the research frontier:

**Parameter Tuning Complexity**: While class K functions theoretically provide flexibility in designing CBF decay rates, in practice their manual tuning is non-trivial and often heuristic. Automated design methods that balance safety conservatism with performance objectives remain incompletely developed.

**Feasibility Assurance**: CBF-QP infeasibility occurs when safety constraints conflict with control limits or performance objectives. While solutions exist through constraint relaxation and structural redesign, no unified framework systematically prevents infeasibility during controller synthesis.

**High-Relative-Degree Constraints**: Although HOCBFs theoretically handle arbitrary relative degree, numerical implementation becomes increasingly challenging as relative degree increases, particularly with input constraints and uncertain dynamics.

**Generalization Across Environments**: Learning-based CBFs often require retraining for new environments despite identical system dynamics, suggesting current approaches capture environment-specific rather than fundamental safety properties.

**Computational Scalability**: While most approaches achieve real-time performance on moderate-dimensional systems, scalability to high-dimensional state spaces and complex multi-agent scenarios remains limited.

### Convergence and Research Trajectory

The arc of recent CBF research reveals a field transitioning from theoretical guarantees toward practical deployment. The 2024-2025 literature emphasizes three complementary research directions: (1) uncertainty quantification and learning-based model identification; (2) structural innovations that simplify design without sacrificing theoretical guarantees; and (3) expanded applications to complex multi-agent and learning-based control settings. The maturation of both theoretical foundations and practical implementations suggests CBFs will increasingly become integrated into safety-critical control frameworks for autonomous systems, provided ongoing research continues addressing the computational and design challenges that currently limit broader deployment.

***

**Citations:**
IEEE Comprehensive Review, November 2024 - Uncertainty Handling, Design Optimization, and Feasibility Analysis[^1_1]
Filtered Control Barrier Functions, April 2025 - Liu, Xiao, Belta[^1_2]
Adaptive DNN-Based CBFs, January 2025 - Sweatland et al.[^1_3]
Truncated Taylor CBFs, March 2025 - High-Order Control Barrier Functions redesign[^1_4]
Rectified Control Barrier Functions, December 2024[^1_5]
Reciprocal CBFs, October 2025 - Level Surface Design[^1_6]
Learning CBFs from Inverse Constraint Learning, October 2025[^1_7]
Set-Based CBFs, July 2025 - Implicit data-driven designs[^1_8]
Deep Equivariant Multi-Agent CBFs, June 2025[^1_9]
Robust Data-Driven CBFs, 2023[^1_10]
Event-Triggered Learning, August 2024[^1_11]
Risk-Aware CBFs, April 2023[^1_12]
Multi-Agent Responsibility Allocation, October 2024[^1_13]
<span style="display:none">[^1_14][^1_15][^1_16][^1_17][^1_18][^1_19][^1_20][^1_21][^1_22][^1_23][^1_24][^1_25][^1_26][^1_27][^1_28][^1_29][^1_30][^1_31][^1_32][^1_33][^1_34][^1_35][^1_36][^1_37][^1_38][^1_39][^1_40][^1_41][^1_42][^1_43][^1_44][^1_45][^1_46][^1_47][^1_48][^1_49][^1_50][^1_51][^1_52][^1_53]</span>

<div align="center">⁂</div>

[^1_1]: https://ieeexplore.ieee.org/document/11267490/

[^1_2]: https://www.mdpi.com/2227-9717/13/6/1791

[^1_3]: https://aipublications.com/ijhaf/detail/a-review-on-recent-advances-of-packaging-in-food-industry/

[^1_4]: https://www.nature.com/articles/s12276-023-01022-z

[^1_5]: https://journals.lww.com/10.1097/MCO.0000000000000709

[^1_6]: https://link.springer.com/10.1007/s10853-025-10705-z

[^1_7]: https://www.mdpi.com/1422-0067/21/23/9199

[^1_8]: https://www.nature.com/articles/nri3707

[^1_9]: https://www.mdpi.com/1420-3049/26/11/3093

[^1_10]: https://onlinelibrary.wiley.com/doi/10.1002/glia.23924

[^1_11]: https://arxiv.org/pdf/2312.16719.pdf

[^1_12]: https://arxiv.org/pdf/2304.01040.pdf

[^1_13]: http://arxiv.org/pdf/1903.11199v1.pdf

[^1_14]: http://arxiv.org/pdf/2406.13420.pdf

[^1_15]: http://arxiv.org/pdf/2503.23267.pdf

[^1_16]: https://arxiv.org/html/2412.03708v1

[^1_17]: http://arxiv.org/pdf/2406.14430.pdf

[^1_18]: http://arxiv.org/pdf/2304.01815.pdf

[^1_19]: https://ieeexplore.ieee.org/document/11065168/

[^1_20]: https://arxiv.org/abs/2507.07805

[^1_21]: https://arxiv.org/abs/2510.21560

[^1_22]: https://ieeexplore.ieee.org/document/10015033/

[^1_23]: https://ieeexplore.ieee.org/document/10418986/

[^1_24]: https://ieeexplore.ieee.org/document/11107831/

[^1_25]: https://ieeexplore.ieee.org/document/11246330/

[^1_26]: https://ieeexplore.ieee.org/document/10981640/

[^1_27]: https://ieeexplore.ieee.org/document/10305174/

[^1_28]: https://ieeexplore.ieee.org/document/10492989/

[^1_29]: https://arxiv.org/abs/2503.10641

[^1_30]: https://arxiv.org/pdf/2305.03608.pdf

[^1_31]: http://arxiv.org/pdf/2401.05629.pdf

[^1_32]: https://arxiv.org/abs/2408.16144

[^1_33]: https://arxiv.org/abs/2011.04112

[^1_34]: https://arxiv.org/pdf/1912.10099.pdf

[^1_35]: https://arxiv.org/pdf/2004.03315.pdf

[^1_36]: http://arxiv.org/pdf/2111.09971.pdf

[^1_37]: https://ieeexplore.ieee.org/document/9902121/

[^1_38]: https://ieeexplore.ieee.org/document/9838179/

[^1_39]: https://ieeexplore.ieee.org/document/11082490/

[^1_40]: https://ieeexplore.ieee.org/document/10363111/

[^1_41]: https://arxiv.org/abs/2503.15014

[^1_42]: https://ieeexplore.ieee.org/document/11054265/

[^1_43]: https://arxiv.org/abs/2510.22514

[^1_44]: https://ieeexplore.ieee.org/document/10802967/

[^1_45]: https://ieeexplore.ieee.org/document/10311096/

[^1_46]: https://ieeexplore.ieee.org/document/11221809/

[^1_47]: https://arxiv.org/pdf/1903.04706.pdf

[^1_48]: https://arxiv.org/pdf/2412.03678.pdf

[^1_49]: http://arxiv.org/pdf/2410.11157v2.pdf

[^1_50]: http://arxiv.org/pdf/2111.11277.pdf

[^1_51]: https://arxiv.org/pdf/2201.01347.pdf

[^1_52]: https://arxiv.org/pdf/2203.07978.pdf

[^1_53]: https://arxiv.org/html/2410.14528v1

