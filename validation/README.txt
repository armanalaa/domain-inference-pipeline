Expert Validation Supplementary Material

This Zenodo package contains supplementary material for the expert validation of the proposed data mesh domain discovery pipeline. The validation was designed to assess whether the pipeline can infer coherent business domains from data lake schemas and assign meaningful domain labels.

Files:


1. The output of the pipeline for each data lake (DomainMiner_Datalakes.zip)

2. Considering each data lake, the Entity relationship diagrams (ERDs) for the main schema and the ERD and the label name, for each inferred domain (DomainMiner_ERDs.zip)


3.  Blank copy of the final questionnaire shown to the experts (Questionnaire.pdf)
  

4. Anonymized and coded expert responses. Respondents are identified only as E1, E2, ..., E16. Names, email addresses, timestamps, affiliations, and other identifying metadata were removed. (Expert_Validation_Responses_Anonymized.xlsx)
   


Validation protocol

- Number of experts: 16.
- Required field of expertise: Data Management, Data Architecture, Business Process Management, Domain Modeling, database design, data modeling, data engineering, data governance, business intelligence, enterprise architecture, software architecture, or related fields.
- Selection criteria: participants were selected based on academic or professional experience relevant to interpreting database schemas, entity-relationship diagrams (ERDs), data models, enterprise systems, or business-domain-oriented data ownership.
- Evaluation task: experts inspected, for each selected data lake, the ERD of the complete data lake schema and the ERDs of the domains inferred by the pipeline. Each inferred domain was presented together with its automatically generated label. Experts then evaluated the quality of the inferred domains and labels.
- Questionnaire structure: the questionnaire contained 8 questions. The first 3 questions collected expert background information: role or profession, expertise level, and experience interpreting database schemas or ERDs. The remaining 5 questions evaluated domain coherence, domain granularity, practical usability, label accuracy, and the overall ability of the model to infer and label business domains.
- Rating scale: the 5 validation questions used a five-point Likert scale: Very poor, Poor, Fair, Good, and Excellent. For quantitative analysis, these responses were encoded as scores from 1 to 5, respectively, where 5 is the maximum score.

How to interpret the anonymized responses:

- Expert_ID identifies each respondent with a non-identifying code.
- Role_Category groups respondents into broad non-identifying professional categories.
- Expertise_Level reports the self-assessed level of expertise in the relevant field.
- ERD_Interpretation_Experience reports self-assessed experience interpreting database schemas or ERDs.
- Domain_Coherence evaluates whether tables grouped in each inferred domain support the same business capability.
- Domain_Granularity evaluates whether inferred domains have an appropriate size and scope for a single business responsibility.
- Practical_Usability evaluates whether inferred domains could be used as a starting point for assigning real data ownership.
- Label_Accuracy evaluates whether generated labels correctly describe the business purpose of the corresponding domains.
- Overall_Model_Ability evaluates the overall ability of the model to infer business domains and assign meaningful labels.

