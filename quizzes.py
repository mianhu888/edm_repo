import os
import re
from pprint import pprint
import sys
import json


class QuizResult:
    score: float
    correct: bool
    points_possible: int
    feedbacks: {str: str}
    graded_successfully: bool
    submission_body: dict
    error: str

    def __init__(self, s, c, p, f, g, b, e):
        self.score = s
        self.correct = c
        self.points_possible = p
        self.feedbacks = f
        self.graded_successfully = g
        self.submission_body = b
        self.error = e

class Feedback:
    message: str
    correct: bool
    score: float
    status: str


def try_parse_file(contents: str, filename: str):
    try:
        return True, json.loads(contents)
    except json.JSONDecodeError as e:
        return False, f"No JSON could be parsed from {filename}.\n{str(e)}"


def process_quiz_str(body: str, checks: str, submission_body: str) -> QuizResult:
    """ (status, correct, score, points, feedbacks, submission_body)"""
    body_ready, body = try_parse_file(body, "Quiz Body")
    checks_ready, checks = try_parse_file(checks, "Quiz Checks")
    student_ready, student = try_parse_file(submission_body or "{}", "Student Submission")
    if not body_ready:
        return QuizResult(0, 0, 0, {}, False, None, body)
    if not checks_ready:
        return QuizResult(0, 0, 0, {}, False, None, checks)
    if not student_ready:
        return QuizResult(0, 0, 0, {}, False, None, student)
    return process_quiz(body, checks, student)


def process_quiz(body: dict, checks: dict, submission_body: dict) -> QuizResult:
    # Extract the requisite data within the objects
    student_answers = submission_body.get('studentAnswers', {})
    checks = checks.get('questions', {})
    questions = body.get('questions', {})
    # For each question in the on_run, run the evaluation criteria
    total_score, total_points = 0., 0.
    total_correct = True
    feedbacks = {}
    for question_id, question in questions.items():
        student = student_answers.get(question_id)
        if student is None:
            # Hack - for now we just skip missing student submissions
            continue
        check = checks.get(question_id, {})
        points = question.get('points', 1)
        total_points += points
        checked_question = check_quiz_question(question, check, student)
        if checked_question is None:
            feedbacks[question_id] = {"message": "Unknown Type: " + question.get('type'),
                                      "correct": None, "score": 0, "status": "error"}
        else:
            score, correct, feedback = checked_question
            #print(question_id, score)
            total_score += score*points
            total_correct = total_correct and correct
            message = str(feedback)
            feedbacks[question_id] = { 'message': message, 'correct': correct, 'score': score, 'status': 'graded' }
    # Report back the final score and feedback objects
    #print(total_score, total_points)
    return QuizResult(total_score / total_points if total_points else 0, total_correct, total_points, feedbacks, True, submission_body, None)


def check_quiz_question(question, check, student) -> (float, bool, list):
    if question.get('type') == 'true_false_question':
        correct = student.lower() == str(check.get('correct')).lower()
        return correct, correct, check.get('wrong') if not correct else "Correct"
    elif question.get('type') == 'matching_question':
        corrects = [student_part == correct_part
                    for student_part, correct_part in zip(student, check.get('correct', []))]
        feedbacks = [feedback.get(student_part)
                     for student_part, feedback in zip(student, check.get('feedback', []))]
        message = "\n<br>".join(map(str, feedbacks)) if any(map(bool, feedbacks)) else ("Correct" if all(corrects) else 'Incorrect')
        return sum(corrects)/len(corrects) if corrects else 0, all(corrects), message
    elif question.get('type') == 'multiple_choice_question':
        correct = student == check.get('correct')
        return correct, correct, check.get('feedback', {}).get(student) if not correct else "Correct"
    elif question.get('type') == 'multiple_answers_question':
        correct = set(student) == set(check.get('correct', []))
        answers = question.get('answers', [])
        corrects = [(s in check.get('correct', [])) == (s in student)
                    for s in answers]
        return sum(corrects)/len(answers), correct, check.get('wrong_any', 'Incorrect') if not correct else 'Correct'
    elif question.get('type') == 'multiple_dropdowns_question':
        corrects = [student.get(blank_id) == answer
                    for blank_id, answer in check.get('correct', {}).items()]
        #feedbacks = "<br>\n".join(check.get('wrong', {}).get(blank_id, {}).get(answer, 'Correct')
        #             for blank_id, answer in student.items())
        feedback = check.get('wrong_any', 'Incorrect') if not all(corrects) else "Correct"
        return sum(corrects) / len(corrects) if corrects else 0, all(corrects), feedback
    elif question.get('type') in ('short_answer_question', 'numerical_question'):
        wrong_any = check.get('wrong_any', "Incorrect")
        if 'correct_exact' in check:
            correct = student in check['correct_exact']
            feedback = check.get('feedback', {}).get(student, wrong_any)
        elif 'correct_regex' in check:
            correct = any(re.match(reg, student) for reg in check['correct_regex'])
            feedback = [check.get('feedback', {}).get(reg) for reg in check['correct_regex'] if re.match(reg, student)]
            feedback = feedback[0] if feedback else wrong_any
        else:
            return 0, False, "Unknown Short Answer Question Check: "+ str(check)
        return correct, correct, feedback if not correct else "Correct"
    #elif question.get('type') == 'numerical_question':
    #    pass
    elif question.get('type') == 'fill_in_multiple_blanks_question':
        if 'correct_exact' in check:
            corrects = [student.get(blank_id) in answer
                        for blank_id, answer in check.get('correct_exact', {}).items()]
        elif 'correct_regex' in check:
            corrects = [any(re.match(reg, student.get(blank_id)) for reg in answer)
                        for blank_id, answer in check.get('correct_exact', {}).items()]
        else:
            return 0, False, "Unknown Fill In Multiple Blanks Question Check: "+ str(check)
        feedback = check.get('wrong_any', 'Incorrect') if not all(corrects) else 'Correct'
        return sum(corrects) / len(corrects) if corrects else 0, all(corrects), feedback
    elif question.get('type') in ('text_only_question', 'essay_question'):
        return 1, True, "Correct"
    return None


def convert_quiz_question(question) -> (dict, dict):
    """

    :param question:
    :return: (body, checks)
    """
    body, check = {}, {}
    body['id'] = question['question_name']
    body['type'] = question['question_type']
    body['points'] = question['points_possible']
    body['body'] = question['question_text']
    check['id'] = question['question_name']
    if question.get('incorrect_comments_html'):
        check['wrong_any'] = question.get('incorrect_comments_html')
    # Actual per-question handling
    if question['question_type'] == 'true_false_question':
        answers = question['answers']
        for answer in answers:
            check['correct'] = (answer['text'] == 'True') == (answer['weight'] == 100)
            if answer.get('comments'):
                check['wrong'] = answer.get('comments')
    elif question['question_type'] == 'matching_question':
        answers = [statement['left'] for statement in question['answers']]
        answers.extend([text for text in
                        (question.get('matching_answer_incorrect_matches') or '').split('\n')
                       if text])
        body['answers'] = answers
        body['statements'] = [answer['text'] for answer in question['matches']]
        check['correct'] = {statement['right']: statement['left'] for statement in question['answers']}
        check['wrong'] = {statement.get('comments', '') for statement in question['answers']}
    elif question['question_type'] == 'multiple_choice_question':
        body['answers'] = [answer['text'] for answer in question['answers']]
        check['correct'] = [statement['text'] for statement in question['answers']
                            if statement['weight'] == 100][0]
        check['feedback'] = {
            statement['text']: statement['comments'] for statement in question['answers']
            if statement['weight'] == 0 and statement.get('comments')
        }
    elif question['question_type'] == 'multiple_answers_question':
        if question['question_name'] == 'DetermineAppropriateDataFlow':
            pprint(question)
        body['answers'] = [answer.get('html', answer.get('text')) for answer in question['answers']]
        check['correct'] = [statement.get('html', statement.get('text')) for statement in question['answers'] if statement['weight'] == 100]
        # TODO: Shouldn't I utilize these comments?
    elif question['question_type'] == 'multiple_dropdowns_question':
        answers = [answer['text'] for answer in question['answers']]
        answers.extend([text for text in
                        (question.get('matching_answer_incorrect_matches') or '').split('\n')
                        if text])
        body['answers'] = {statement['blank_id']: answers for statement in question['answers']}
        check['correct'] = {statement['blank_id']: statement['text']
                            for statement in question['answers']}
        check['wrong'] = {statement['blank_id']: statement['comments']
                          for statement in question['answers']
                          if statement.get('comments')}
    elif question['question_type'] == 'short_answer_question':
        check['correct_exact'] = [statement['text'] for statement in question['answers']]
    elif question['question_type'] == 'numerical_question':
        pprint(question)
        # TODO: Find one
    elif question['question_type'] == 'fill_in_multiple_blanks_question':
        check['correct'] = {}
        for answer in question['answers']:
            blank_id = answer['blank_id']
            if blank_id not in check['correct']:
                check['correct'][blank_id] = []
            check['correct'][blank_id].append(answer['text'])
    return body, check


def clean_name(filename):
    return secure_filename(filename).replace(" ", "_").replace("-", "_").replace("__", "_")
