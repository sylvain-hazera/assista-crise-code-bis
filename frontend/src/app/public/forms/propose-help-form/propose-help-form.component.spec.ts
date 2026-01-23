import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ProposeHelpFormComponent } from './propose-help-form.component';

describe('ProposeHelpFormComponent', () => {
  let component: ProposeHelpFormComponent;
  let fixture: ComponentFixture<ProposeHelpFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProposeHelpFormComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ProposeHelpFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
